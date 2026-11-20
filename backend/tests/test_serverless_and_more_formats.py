"""Serverless behaviour (several instances, no shared disk) and the formats added for uploads: spreadsheets, statistics files,
scientific arrays, XML records, tar/7z/bzip2/xz and archives inside archives."""
import bz2
import http.server
import io
import json
import tarfile
import threading
import urllib.request
import zipfile

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app import durable
from app.discovery import analysis, resolve, store
from app.main import app

from .fixtures_formats import record

ROWS = pd.DataFrame({"date": pd.date_range("2021-01-01", periods=120, freq="D").strftime("%Y-%m-%d"),
                     "borough": ["BROOKLYN", "QUEENS", "BRONX"] * 40, "injured": np.arange(120) % 5, "lat": np.linspace(40.5, 40.9, 120)})


@pytest.fixture()
def client():
    with TestClient(app) as c:
        store.load_seeds()
        durable.reset_for_tests()
        resolve._CACHE.clear()
        store._invalidate()
        yield c
        durable.reset_for_tests()
        store._invalidate()


def _dataset():
    rec = record("zenodo.crashes", "NYC crashes", "Zenodo", "https://example.org/crashes")
    store.save_curated_record(rec)
    store._invalidate()
    return rec["id"]


def _upload(client, name: str, data: bytes) -> dict:
    rid = _dataset()
    r = client.post(f"/api/datasets/{rid}/analyze/upload", files={"file": (name, data)})
    assert r.status_code == 202, r.text
    run_id = r.json()["runId"]
    for _ in range(400):
        run = client.get(f"/api/analyses/{run_id}").json()
        if run["status"] in ("succeeded", "failed"):
            return run
        threading.Event().wait(0.05)
    raise AssertionError("analysis did not finish")


def _csv() -> bytes:
    return ROWS.to_csv(index=False).encode()


def _zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for k, v in files.items():
            z.writestr(k, v)
    return buf.getvalue()


def _tar(files: dict[str, bytes], mode: str) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode=mode) as t:
        for k, v in files.items():
            info = tarfile.TarInfo(k)
            info.size = len(v)
            t.addfile(info, io.BytesIO(v))
    return buf.getvalue()


# ---------------------------------------------------------------- one instance finds, another opens
def test_a_live_result_found_by_one_instance_opens_on_another(client, monkeypatch):
    """Vercel instances don't share /tmp: the live-search cache of the instance that searched is invisible to the next one."""
    monkeypatch.setattr(store, "SHARE_LOCAL", True)
    raw = {"id": "kaggle.someone-nyc-crashes", "title": "NYC crashes", "description": "Crash records", "publisher": "someone (via Kaggle)",
           "provider": "Kaggle", "providerId": "someone/nyc-crashes", "canonicalUrl": "https://www.kaggle.com/datasets/someone/nyc-crashes",
           "sourceLinks": [], "tags": ["traffic"], "purposes": [], "characteristics": [], "formats": {"values": [], "status": "unknown"},
           "access": {"method": "sign-in", "signInRequired": True, "status": "provider-reported"},
           "license": {"name": None, "commercialUse": "unknown", "status": "unknown"},
           "coverage": {"temporal": {"status": "unknown"}, "spatial": {"scope": "unknown", "status": "unknown"}},
           "schemaStatus": "unknown", "fields": [], "size": {"rows": None, "bytes": None}, "limitations": []}
    ids = store.upsert_live([raw], "kaggle", "nyc crashes")
    store.record_live_run("nyc crashes", "kaggle", "ok", "1 results", 1, 5)
    # The other instance: same database, empty local cache.
    with store.connect() as con:
        for t in ("records", "records_fts", "live_hits", "live_runs"):
            con.execute(f"delete from {t} where {'id' if t.startswith('records') else 'query'} in (?, ?)", (ids[0], "nyc crashes"))
    store._invalidate()
    store._hydrated.clear()
    assert ids[0] not in store.all_records()
    r = client.get(f"/api/datasets/{ids[0]}")
    assert r.status_code == 200, r.text
    assert store.live_run("nyc crashes", "kaggle")["status"] == "ok"  # the provider isn't asked again
    assert ids[0] in store.live_hits("nyc crashes")
    up = client.post(f"/api/datasets/{ids[0]}/analyze/upload", files={"file": ("crashes.csv", _csv())})
    assert up.status_code == 202, up.text


def test_kaggle_credentials_are_not_sent_to_the_storage_host_a_download_redirects_to():
    seen: dict[str, str | None] = {}

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            seen[f"{self.server.server_port}{self.path}"] = self.headers.get("Authorization")
            if self.path == "/download":
                self.send_response(302)
                self.send_header("Location", f"http://localhost:{storage.server_port}/signed?sig=1")
                self.end_headers()
                return
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"a,b\n1,2\n")

    api = http.server.HTTPServer(("127.0.0.1", 0), H)
    storage = http.server.HTTPServer(("127.0.0.1", 0), H)
    for s in (api, storage):
        threading.Thread(target=s.serve_forever, daemon=True).start()
    try:
        urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{api.server_port}/download",
                                                      headers={"Authorization": "Basic secret"}), timeout=5).read()
    finally:
        api.shutdown()
        storage.shutdown()
    assert seen[f"{api.server_port}/download"] == "Basic secret"
    assert seen[f"{storage.server_port}/signed?sig=1"] is None


def test_a_direct_upload_in_queue_mode_finishes_in_the_request(client, monkeypatch):
    """On Vercel a thread started after the response is frozen: the upload must be analyzed before the request returns."""
    monkeypatch.setattr(analysis, "RUN_MODE", "queue")
    rid = _dataset()
    r = client.post(f"/api/datasets/{rid}/analyze/upload", files={"file": ("crashes.zip", _zip({"a/crashes.csv": _csv()}))})
    assert r.status_code == 202
    assert client.get(f"/api/analyses/{r.json()['runId']}").json()["status"] == "succeeded"


# ---------------------------------------------------------------- formats
def test_excel_upload_is_analyzed_not_listed_as_a_zip(client):
    buf = io.BytesIO()
    ROWS.to_excel(buf, index=False)
    run = _upload(client, "crashes.xlsx", buf.getvalue())
    assert run["status"] == "succeeded" and run["report"]["kind"] == "table", run.get("error")
    assert {c["name"] for c in run["report"]["columns"]} >= {"borough", "injured"}


@pytest.mark.parametrize("name,maker", [
    ("crashes.ods", lambda p: ROWS.to_excel(p, engine="odf", index=False)),
    ("crashes.dta", lambda p: ROWS.to_stata(p, write_index=False)),
])
def test_spreadsheet_and_statistics_files(client, tmp_path, name, maker):
    p = tmp_path / name
    maker(p)
    run = _upload(client, name, p.read_bytes())
    assert run["status"] == "succeeded" and run["report"]["kind"] == "table", run.get("error")
    assert run["report"]["converted"]["converted_from"]
    assert len(run["report"]["columns"]) == 4


def test_netcdf3_grid_becomes_a_long_table(client, tmp_path):
    from scipy.io import netcdf_file

    p = tmp_path / "sst.nc"
    f = netcdf_file(str(p), "w")
    for d, n in (("time", 4), ("lat", 5), ("lon", 6)):
        f.createDimension(d, n)
        f.createVariable(d, "f4", (d,))[:] = np.arange(n)
    f.createVariable("sst", "f4", ("time", "lat", "lon"))[:] = np.random.rand(4, 5, 6)
    f.close()
    run = _upload(client, "sst.nc", p.read_bytes())
    assert run["status"] == "succeeded" and run["report"]["kind"] == "table", run.get("error")
    assert {c["name"] for c in run["report"]["columns"]} == {"time", "lat", "lon", "sst"}
    assert run["report"]["rows_total"] == 120


def test_hdf5_records_become_a_table(client, tmp_path):
    h5py = pytest.importorskip("h5py")
    p = tmp_path / "m.h5"
    rec = np.zeros(50, dtype=[("id", "i4"), ("value", "f8")])
    rec["id"] = np.arange(50)
    with h5py.File(p, "w") as h:
        h.create_dataset("measurements", data=rec)
    run = _upload(client, "m.h5", p.read_bytes())
    assert run["status"] == "succeeded" and run["report"]["kind"] == "table", run.get("error")
    assert run["report"]["rows_total"] == 50


def test_xml_records_become_a_table(client):
    xml = "<rows>" + "".join(f"<row id='{i}'><borough>B{i % 3}</borough><injured>{i % 4}</injured></row>" for i in range(30)) + "</rows>"
    run = _upload(client, "crashes.xml", xml.encode())
    assert run["status"] == "succeeded" and run["report"]["kind"] == "table", run.get("error")
    assert {c["name"] for c in run["report"]["columns"]} == {"@id", "borough", "injured"}


@pytest.mark.parametrize("name,data", [
    ("crashes.tar.gz", lambda: _tar({"x/crashes.csv": _csv()}, "w:gz")),
    ("crashes.tar.bz2", lambda: _tar({"crashes.csv": _csv()}, "w:bz2")),
    ("crashes.tar.xz", lambda: _tar({"crashes.csv": _csv()}, "w:xz")),
    ("crashes.csv.bz2", lambda: bz2.compress(_csv())),
    ("nested.zip", lambda: _zip({"inner/part.zip": _zip({"crashes.csv": _csv()}), "README.txt": b"hi"})),
    ("zip-of-tgz.zip", lambda: _zip({"inner/data.tgz": _tar({"crashes.csv": _csv()}, "w:gz")})),
])
def test_archives_of_every_kind_reach_the_table(client, name, data):
    run = _upload(client, name, data())
    assert run["status"] == "succeeded" and run["report"]["kind"] == "table", (run.get("error"), run["report"].get("inspection"))
    assert run["report"]["rows_total"] == 120


def test_tar_members_cannot_escape_or_link(client):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as t:
        for n in ("../evil.csv", "/abs.csv"):
            info = tarfile.TarInfo(n)
            info.size = len(_csv())
            t.addfile(info, io.BytesIO(_csv()))
        link = tarfile.TarInfo("link.csv")
        link.type = tarfile.SYMTYPE
        link.linkname = "/etc/passwd"
        t.addfile(link)
        info = tarfile.TarInfo("ok/crashes.csv")
        info.size = len(_csv())
        t.addfile(info, io.BytesIO(_csv()))
    run = _upload(client, "mixed.tar", buf.getvalue())
    assert run["status"] == "succeeded", run.get("error")
    names = json.dumps(run["report"].get("archive", {}))
    assert "passwd" not in names and "../" not in names


def test_rar_says_what_to_do(client):
    run = _upload(client, "data.rar", b"Rar!\x1a\x07\x00" + b"\x00" * 64)
    assert run["status"] == "failed" and "Extract it" in run["error"]


def test_single_image_gets_an_image_report(client):
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (32, 24), (10, 200, 30)).save(buf, "PNG")
    run = _upload(client, "photo.png", buf.getvalue())
    assert run["status"] == "succeeded" and run["report"]["kind"] == "images", run.get("error")
