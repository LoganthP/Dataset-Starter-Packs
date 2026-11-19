"""Large transfers, archives, the format registry (images, SINEX, Parquet pairs) and Connect Kaggle.

Everything here runs against fixtures served by a local HTTP server with Range support; no live provider is contacted.
"""
import gzip
import io
import json
import time
import zipfile

import pytest
from fastapi.testclient import TestClient

from app import durable, kaggle_connect
from app.discovery import analysis, archive, limits, resolve, store
from app.discovery.adapters import huggingface
from app.discovery.formats import images as images_mod
from app.discovery.formats import sinex as sinex_mod
from app.main import app

from .fixtures_formats import STATIONS, Server, basic, dota_zip, fradra_pair, record, ships_zip, sinex_text


@pytest.fixture()
def server(monkeypatch):
    s = Server()
    monkeypatch.setenv("DSP_ALLOW_LOCAL_SOURCES", "1")
    monkeypatch.setenv("KAGGLE_API_BASE", s.base)
    monkeypatch.setattr(huggingface, "HUB", s.base)
    yield s
    s.close()


@pytest.fixture()
def client(server):
    with TestClient(app) as c:
        store.load_seeds()
        durable.reset_for_tests()
        resolve._CACHE.clear()
        store._invalidate()
        yield c
        durable.reset_for_tests()
        store._invalidate()


def wait(client, run_id, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        run = client.get(f"/api/analyses/{run_id}").json()
        if run.get("status") in ("succeeded", "failed"):
            return run
        time.sleep(0.05)
    raise AssertionError("analysis did not finish")


def add(rec):
    store.save_curated_record(rec)
    store._invalidate()
    resolve._CACHE.clear()
    return rec["id"]


def listed(server, path, data, rid, title, provider="Zenodo"):
    server.files[path] = data
    return add(record(rid, title, provider, f"{server.base}/records/{rid}", files=[{"url": f"{server.base}{path}", "name": path.rsplit('/', 1)[-1]}]))


# ---------------------------------------------------------------- Ships (the screenshot: "largest file in the ZIP is over the size limit")
def test_ships_zip_upload_reaches_the_image_analyzer(client, monkeypatch):
    monkeypatch.setattr(images_mod, "MAX_ANNOTATION_JSON", 1_000_000)  # the real shipsnet.json is hundreds of MB: a pixel dump, not labels
    rid = add(record("kaggle.rhammell-ships-in-satellite-imagery", "Ships in Satellite Imagery", "Kaggle",
                     "https://www.kaggle.com/datasets/rhammell/ships-in-satellite-imagery"))
    data = ships_zip()
    run = wait(client, client.post(f"/api/datasets/{rid}/analyze/upload", files={"file": ("archive.zip", io.BytesIO(data), "application/zip")}).json()["runId"])
    assert run["status"] == "succeeded", run["error"]
    rep = run["report"]
    assert rep["kind"] == "images" and rep["handler"] == "images" and rep["coverage"] == "full"
    im = rep["images"]
    assert im["total"] == 122 and im["analyzed"] == 122 and im["unreadable"] == 0
    assert dict(im["class_images"]) == {"0": 90, "1": 30} and im["label_source"].startswith("file-name prefix")
    assert ["80×80", 120] in im["dimensions"] and im["geotagged"] == 120
    assert rep["insights"]["coordinates"]["valid"] == 120  # lon/lat from the file names -> map
    assert rep["archive"]["members_total"] == 123 and "shipsnet.json" not in rep["archive"]["selected"]
    assert rep["transferred_bytes"] == len(data) and rep["archive"]["expanded_bytes"] > len(data)
    assert "Image dataset: extracting 122 file(s)" in run["log"]


def test_quick_sample_of_a_large_zip_offers_prepare_then_samples(client, server, monkeypatch):
    """SatCen screenshot: 'Use Full analysis' was the only way out. Now: Prepare archive and run sample, or Full."""
    data = dota_zip()
    monkeypatch.setattr(analysis, "QUICK_MAX_BYTES", len(data) // 2)
    rid = listed(server, "/files/satcen_skiff_detection_dataset.zip", data, "doi.10.5281--zenodo.10461496", "SatCen Skiff Detection Dataset")
    server.no_ranges.add("/files/satcen_skiff_detection_dataset.zip")  # this provider ignores Range: the archive must come whole
    url = client.get(f"/api/datasets/{rid}/files").json()["files"][0]["url"]
    r = client.post(f"/api/datasets/{rid}/analyze", json={"fileUrl": url})
    assert r.status_code == 422
    d = r.json()["detail"]
    assert d["kind"] == "too_large" and d["detail"]["limit"] == "quick_sample" and d["detail"]["actions"] == ["prepare_archive_sample", "full"]
    assert d["detail"]["measuredBytes"] == len(server.files["/files/satcen_skiff_detection_dataset.zip"])
    assert client.get("/api/analyses").json() == []  # nothing started
    monkeypatch.setattr(images_mod, "SAMPLE_IMAGES", 10)
    run = wait(client, client.post(f"/api/datasets/{rid}/analyze", json={"fileUrl": url, "prepare": True}).json()["runId"])
    assert run["status"] == "succeeded", run["error"]
    rep = run["report"]
    im = rep["images"]
    assert rep["coverage"] == "sample" and im["total"] == 40 and im["analyzed"] == 10 and "systematic sample" in rep["sample_method"]
    assert im["annotation_format"] == "dota" and dict(im["objects_by_class"])["skiff"] > 0
    assert im["previews"] and im["previews"][0]["shapes"] and len(im["previews"][0]["shapes"][0]["points"]) == 4
    assert all(0 <= x <= 1 and 0 <= y <= 1 for x, y in im["previews"][0]["shapes"][0]["points"])
    assert rep["archive"]["extracted_files"] < rep["archive"]["members_total"]  # only what the sample needs
    full = wait(client, client.post(f"/api/datasets/{rid}/analyze", json={"fileUrl": url, "mode": "full"}).json()["runId"])
    fim = full["report"]["images"]
    assert full["report"]["coverage"] == "full" and fim["analyzed"] == 40 and fim["with_objects"] == 15 and fim["annotated"] == 40
    assert fim["objects"] == sum(1 + i % 3 for i in range(15))


def test_remote_archive_listing_without_download(client, server):
    rid = listed(server, "/files/ships.zip", ships_zip(ships=3, no_ships=9, json_bytes=10_000), "z.ships", "Ships archive")
    url = client.get(f"/api/datasets/{rid}/files").json()["files"][0]["url"]
    info = client.post(f"/api/datasets/{rid}/inspect", json={"fileUrl": url}).json()
    assert info["detected"] == "zip" and info["rangeReads"] and info["memberCount"] == 15
    assert info["suggested"]["handler"] == "images" and {t["type"] for t in info["types"]} >= {"png", "json"}
    got = [r for r in server.requests if r[0] == "/files/ships.zip"]
    assert len(got) <= 6  # a few ranged reads, not the archive


# ---------------------------------------------------------------- limits
def test_oversized_transfer_is_refused_before_download(client, server, monkeypatch):
    data = ships_zip()
    monkeypatch.setattr(analysis, "MAX_BYTES", len(data) // 2)
    rid = listed(server, "/files/big.zip", data, "z.big", "Big archive")
    url = client.get(f"/api/datasets/{rid}/files").json()["files"][0]["url"]
    r = client.post(f"/api/datasets/{rid}/analyze", json={"fileUrl": url, "mode": "full"})
    d = r.json()["detail"]
    assert r.status_code == 422 and d["kind"] == "too_large" and d["detail"]["limit"] == "transfer"
    assert d["detail"]["measuredBytes"] == len(data) and "transfer limit" in d["message"] and client.get("/api/analyses").json() == []
    assert [p for p, _ in server.requests].count("/files/big.zip") == 1  # only the 8 KB probe


def test_interrupted_download_resumes_with_a_bounded_retry(client, server):
    data = ships_zip(ships=4, no_ships=8, json_bytes=10_000)
    rid = listed(server, "/files/flaky.zip", data, "z.flaky", "Flaky archive")
    server.flaky["/files/flaky.zip"] = 1
    url = client.get(f"/api/datasets/{rid}/files").json()["files"][0]["url"]
    run = wait(client, client.post(f"/api/datasets/{rid}/analyze", json={"fileUrl": url, "mode": "full"}).json()["runId"])
    assert run["status"] == "succeeded", run["error"]
    assert run["file_bytes"] == len(data) and run["report"]["images"]["total"] == 14
    resumed = [r for p, r in server.ranges if p == "/files/flaky.zip" and r.startswith(f"bytes={len(data) // 2}-")]
    assert resumed  # the retry asked only for the missing half


def test_oversized_upload_is_refused(client, monkeypatch):
    monkeypatch.setattr(limits, "MAX_TRANSFER_BYTES", 1000)
    rid = add(record("z.up", "Upload target", "Zenodo", "https://example.org/x"))
    r = client.post(f"/api/datasets/{rid}/analyze/upload", files={"file": ("a.csv", io.BytesIO(b"a,b\n" * 2000), "text/csv")})
    assert r.status_code == 413 and r.json()["detail"]["detail"]["limit"] == "transfer"


def test_over_budget_expanded_archive_fails_cleanly(client, monkeypatch):
    monkeypatch.setattr(limits, "MAX_EXTRACT_BYTES", 1_000_000)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("data/table.csv", "a,b\n" + "1,2\n" * 1_000_000)  # 4 MB expanded, a few KB compressed
    rid = add(record("z.bomb", "Compressed table", "Zenodo", "https://example.org/y"))
    run = wait(client, client.post(f"/api/datasets/{rid}/analyze/upload", files={"file": ("t.zip", io.BytesIO(buf.getvalue()), "application/zip")}).json()["runId"])
    assert run["status"] == "failed" and run["error_kind"] == "too_large" and run["report"] is None
    assert run["error_detail"]["limit"] == "extract" and run["error_detail"]["measuredBytes"] == 4_000_004
    assert "extraction budget" in run["error"] and not (analysis.RUNS_DIR / run["id"] / "x").exists()


def test_unsafe_archive_paths_are_skipped():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("../escape.csv", "a\n1\n")
        z.writestr("/abs.csv", "a\n1\n")
        z.writestr("ok/t.csv", "a\n1\n")
        z.writestr("__MACOSX/._t.csv", "x")
    with zipfile.ZipFile(io.BytesIO(buf.getvalue())) as zf:
        info = archive.inspect_zip(zf)
    assert [m["name"] for m in info["members"]] == ["ok/t.csv"] and len(info["skipped"]) == 2


# ---------------------------------------------------------------- SINEX
def test_sinex_report_has_parsed_stations_and_solutions(client):
    rid = add(record("cmr.doris-dpod", "DORIS DPOD", "NASA Earthdata (CMR)", "https://cddis.nasa.gov/archive/doris/products/dpod"))
    text = sinex_text()
    run = wait(client, client.post(f"/api/datasets/{rid}/analyze/upload", files={"file": ("dpod2020.snx", io.BytesIO(text.encode()), "text/plain")}).json()["runId"])
    assert run["status"] == "succeeded", run["error"]
    rep = run["report"]
    sx = rep["sinex"]
    assert rep["kind"] == "sinex" and sx["agency"] == "IDS" and sx["technique"] == "D" and sx["version"] == "2.02"
    assert sx["stations"] == 3 and sx["with_position"] == 3 and sx["with_velocity"] == 3 and sx["located"] == 3
    assert sx["position_sources"] == ["STAX/STAY/STAZ on GRS80"] and sx["frame"] == "terrestrial"
    assert dict(sx["estimate_types"]) == {"STAX": 3, "STAY": 3, "STAZ": 3, "VELX": 3, "VELY": 3, "VELZ": 3}
    assert sx["data_start"].startswith("1993-01-03") and sx["data_end"].startswith("2020-12-31")
    assert sx["sigma_mm"]["median"] == 2.1 and "DPOD2020" in sx["reference"]["DESCRIPTION"]
    rows = {r[0]: r for r in rep["preview"]}
    cols = [c["name"] for c in rep["columns"]]
    for code, _, lat, lon, h, _ in STATIONS:  # XYZ -> lat/lon/h round trip, not the SITE/ID approximation
        r = rows[code]
        assert abs(r[cols.index("latitude")] - lat) < 1e-6 and abs(r[cols.index("longitude")] - lon) < 1e-6 and abs(r[cols.index("height_m")] - h) < 1e-3
    assert rep["insights"]["coordinates"]["valid"] == 3
    hb = rows["HBMB"]
    assert abs(hb[cols.index("vel_north_mm_yr")]) > 1  # velocities rotated to east/north/up in mm/yr


def test_sinex_inside_zip_and_gzip(client):
    rid = add(record("cmr.doris-dpod2", "DORIS DPOD zipped", "NASA Earthdata (CMR)", "https://cddis.nasa.gov/x"))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("dpod/dpod2020_031.snx", sinex_text())
        z.writestr("dpod/README.pdf", b"%PDF-1.4")
    run = wait(client, client.post(f"/api/datasets/{rid}/analyze/upload", files={"file": ("dpod.zip", io.BytesIO(buf.getvalue()), "application/zip")}).json()["runId"])
    assert run["status"] == "succeeded" and run["report"]["kind"] == "sinex" and run["report"]["archive"]["selected"] == ["dpod/dpod2020_031.snx"]
    gz = gzip.compress(sinex_text().encode())
    run = wait(client, client.post(f"/api/datasets/{rid}/analyze/upload", files={"file": ("dpod2020.snx.gz", io.BytesIO(gz), "application/gzip")}).json()["runId"])
    assert run["status"] == "succeeded" and run["report"]["sinex"]["stations"] == 3


def test_sinex_without_xyz_uses_approximate_site_positions():
    parsed = {"header": {}, "reference": {}, "epochs": {}, "estimates": [], "types": {}, "units": {},
              "sites": {("ABMB", "A"): {"code": "ABMB", "description": "Amsterdam", "approx_lat": -37.8, "approx_lon": 77.57, "approx_h": 55.0}}}
    rows, _ = sinex_mod.stations(parsed)
    assert rows[0]["position_source"] == "SITE/ID approximate" and "stax_m" not in rows[0]


# ---------------------------------------------------------------- Hugging Face Parquet pairs
def _hf(server, pairs=3, extra_meta=2):
    sv, md = fradra_pair()
    repo = "FraDra/GEO_satellite_maneuvers"
    prefixes = [f"20251208_00{5 + i}348_70777{i}" for i in range(pairs)]
    page1 = [{"type": "directory", "path": "metadata"}, {"type": "directory", "path": "state_vectors"},
             {"type": "file", "path": ".gitattributes", "size": 10}, {"type": "file", "path": "README.md", "size": 3896}]
    page1 += [{"type": "file", "path": f"metadata/{p}_metadata.parquet", "size": len(md)} for p in prefixes]
    page1 += [{"type": "file", "path": f"metadata/20251222_13{i}000_9_metadata.parquet", "size": len(md)} for i in range(extra_meta)]
    page2 = [{"type": "file", "path": f"state_vectors/{p}_state_vectors.parquet", "size": len(sv), "lfs": {"size": len(sv)}} for p in prefixes]
    tree = f"/api/datasets/{repo}/tree/main"
    server.json[tree] = lambda q: page2 if q.get("cursor") else page1
    server.headers[tree] = lambda q: {} if q.get("cursor") else {"Link": f'<{server.base}{tree}?recursive=true&expand=false&cursor=abc>; rel="next"'}
    for p in prefixes:
        server.files[f"/datasets/{repo}/resolve/main/state_vectors/{p}_state_vectors.parquet"] = sv
        server.files[f"/datasets/{repo}/resolve/main/metadata/{p}_metadata.parquet"] = md
    return add(record("hf.fradra--geo_satellite_maneuvers", "Geo Satellite Maneuvers", "Hugging Face", f"https://huggingface.co/datasets/{repo}",
                      previewProvider="huggingface", providerId=repo)), prefixes


def test_hf_nested_parquet_pairs_are_listed_and_analyzed(client, server, monkeypatch):
    def no_conversion(repo):
        raise huggingface.AdapterError("HTTP 501 from datasets-server")

    monkeypatch.setattr(huggingface, "files", no_conversion)
    rid, prefixes = _hf(server)
    res = client.get(f"/api/datasets/{rid}/files").json()
    pairs = [f for f in res["files"] if f.get("pair_url")]
    assert len(pairs) == 3 and res["pairs"] == 3 and "2 pages" in res["via"]
    assert all(f["name"].startswith("state_vectors/") and f["pair_name"].startswith("metadata/") and f["pair_name"].split("/")[1].split("_metadata")[0] ==
               f["name"].split("/")[1].split("_state_vectors")[0] for f in pairs)
    assert sum(1 for f in res["files"] if f.get("group") == "unpaired") == 2
    one = client.get(f"/api/datasets/{rid}/files", params={"q": prefixes[1], "limit": 5}).json()
    assert one["matched"] == 1 and one["files"][0]["prefix"] == prefixes[1]
    pick = pairs[0]
    run = wait(client, client.post(f"/api/datasets/{rid}/analyze", json={"fileUrl": pick["url"], "pairUrl": pick["pair_url"], "mode": "full"}).json()["runId"])
    assert run["status"] == "succeeded", run["error"]
    rep = run["report"]
    tr = rep["trajectory"]
    assert rep["kind"] == "trajectory" and tr["points_total"] == 400 and tr["time_kind"] == "mjd" and len(tr["points"]) == 400
    assert [m["label"] for m in tr["maneuvers"]] == ["East-West", "North-South"] and tr["maneuvers"][0]["t"].startswith("2025-")
    assert {s["column"] for s in tr["series"]} >= {"x", "y", "z", "semi_major_axis"}
    assert rep["pair"]["file"].endswith("_metadata.parquet") and dict(rep["pair"]["values"])["satellite_mass"] == 3500.0


def test_pair_url_must_be_listed(client, server, monkeypatch):
    monkeypatch.setattr(huggingface, "files", lambda repo: [])
    rid, _ = _hf(server, pairs=1, extra_meta=0)
    pick = client.get(f"/api/datasets/{rid}/files").json()["files"][0]
    run = wait(client, client.post(f"/api/datasets/{rid}/analyze", json={"fileUrl": pick["url"], "pairUrl": "https://evil.example/x.parquet"}).json()["runId"])
    assert run["status"] == "failed" and run["error_kind"] == "not_found"


# ---------------------------------------------------------------- unfamiliar formats
def test_unfamiliar_format_gets_an_inspection_only_report(client):
    rid = add(record("cmr.gpm", "GPM IMERG", "NASA Earthdata (CMR)", "https://example.org/gpm"))
    run = wait(client, client.post(f"/api/datasets/{rid}/analyze/upload", files={"file": ("3B-HHR.nc", io.BytesIO(b"CDF\x01" + b"\x00" * 64), "application/x-netcdf")}).json()["runId"])
    rep = run["report"]
    assert run["status"] == "succeeded" and rep["kind"] == "inspection" and rep["inspection"]["detected"] == "netcdf"
    assert "NetCDF" in rep["inspection"]["next"]
    card = client.get(f"/api/datasets/{rid}").json()["analysis"]
    assert card["scope"] == "Inspection only" and card["kind"] == "inspection"


# ---------------------------------------------------------------- Connect Kaggle
KAGGLE = "rhammell/ships-in-satellite-imagery"


def _kaggle(server, user="loganth", key="k3y"):
    auth = basic(user, key)
    server.require_auth["/api/v1/"] = auth
    server.json["/api/v1/datasets/list"] = [{"ref": "uciml/iris"}]
    data = ships_zip(ships=5, no_ships=15, json_bytes=10_000)
    server.json[f"/api/v1/datasets/list/{KAGGLE}"] = {"datasetFiles": [{"name": "shipsnet.json", "totalBytes": 10_000},
                                                                      {"name": "shipsnet/shipsnet/1__a__-122.1_37.7.png", "totalBytes": 300}]}
    server.files[f"/api/v1/datasets/download/{KAGGLE}"] = data
    return add(record("kaggle.rhammell-ships-in-satellite-imagery", "Ships in Satellite Imagery", "Kaggle", f"https://www.kaggle.com/datasets/{KAGGLE}",
                      providerId=KAGGLE, access={"method": "sign-in", "signInRequired": True})), auth


def test_connect_kaggle_then_fetch_and_analyze_in_app(client, server, monkeypatch):
    monkeypatch.setattr(images_mod, "MAX_ANNOTATION_JSON", 1000)
    rid, auth = _kaggle(server)
    before = client.get(f"/api/datasets/{rid}/files").json()
    assert before["signInRequired"] and before["files"] == [] and before["kaggle"]["connected"] is False
    assert client.post("/api/connections/kaggle", json={"username": "loganth", "key": "k3y"}).status_code == 401  # log in first
    assert client.post("/api/auth/signup", json={"email": "loganth@example.com", "password": "correct horse battery"}).status_code == 201
    bad = client.post("/api/connections/kaggle", json={"username": "loganth", "key": "wrong"})
    assert bad.status_code == 422 and "rejected" in bad.json()["detail"]["message"]
    ok = client.post("/api/connections/kaggle", json={"kaggleJson": json.dumps({"username": "loganth", "key": "k3y"})}).json()
    assert ok["connected"] and ok["account"] == "loganth" and "k3y" not in json.dumps(ok)
    stored = durable.one("select secret from provider_connections")["secret"]
    assert "k3y" not in stored and "loganth" not in stored  # encrypted at rest
    files = client.get(f"/api/datasets/{rid}/files").json()
    assert files["files"][0]["label"].startswith("Entire dataset") and files["kaggle"]["connected"]
    run = wait(client, client.post(f"/api/datasets/{rid}/analyze", json={"fileUrl": files["files"][0]["url"], "mode": "full"}).json()["runId"])
    assert run["status"] == "succeeded", run["error"]
    assert run["report"]["kind"] == "images" and run["report"]["images"]["total"] == 22
    assert "k3y" not in run["log"] and auth not in run["log"] and "k3y" not in json.dumps(run["report"])
    downloads = [a for p, a in server.requests if p == f"/api/v1/datasets/download/{KAGGLE}"]
    assert downloads and all(a == auth for a in downloads)  # credentials only in the Authorization header
    # reports are per user: another account and anonymous visitors don't see it
    mine = client.get("/api/analyses").json()
    assert [r["id"] for r in mine] == [run["id"]]
    client.post("/api/auth/logout")
    assert client.get(f"/api/analyses/{run['id']}").status_code == 404 and client.get("/api/analyses").json() == []
    assert client.get(f"/api/datasets/{rid}").json().get("analysis") is None
    client.post("/api/auth/signup", json={"email": "other@example.com", "password": "another long password"})
    assert client.get(f"/api/analyses/{run['id']}").status_code == 404
    assert client.get("/api/connections/kaggle").json()["connected"] is False
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"email": "loganth@example.com", "password": "correct horse battery"})
    curated = client.get("/api/datasets", params={"scope": "curated", "ready": "analyzed"}).json()["items"]
    assert any(i["id"] == rid and i["analysis"]["runId"] == run["id"] for i in curated)  # reopen from Curated after refresh
    assert client.delete("/api/connections/kaggle").json()["connected"] is False
    assert client.get(f"/api/datasets/{rid}/files", params={"refresh": True}).json()["signInRequired"]


def test_kaggle_consent_is_reported_before_a_job_starts(client, server):
    rid, _ = _kaggle(server)
    server.consent.add(f"/api/v1/datasets/download/{KAGGLE}")
    client.post("/api/auth/signup", json={"email": "c@example.com", "password": "correct horse battery"})
    client.post("/api/connections/kaggle", json={"username": "loganth", "key": "k3y"})
    url = client.get(f"/api/datasets/{rid}/files").json()["files"][0]["url"]
    r = client.post(f"/api/datasets/{rid}/analyze", json={"fileUrl": url, "mode": "full"})
    d = r.json()["detail"]
    assert r.status_code == 422 and d["kind"] == "consent" and d["detail"]["consentUrl"] == f"https://www.kaggle.com/datasets/{KAGGLE}"
    assert client.get("/api/analyses").json() == []
    server.consent.clear()  # accepted on Kaggle: the same selection runs
    assert wait(client, client.post(f"/api/datasets/{rid}/analyze", json={"fileUrl": url, "mode": "full"}).json()["runId"])["status"] == "succeeded"


def test_kaggle_oauth_pkce_flow(client, server, monkeypatch):
    monkeypatch.setenv("KAGGLE_OAUTH_CLIENT_ID", "dsp-test")
    monkeypatch.setenv("DSP_PUBLIC_URL", "http://testserver")
    server.json["/api/v1/oauth2/token"] = {"access_token": "KGAT_abc", "refresh_token": "KGRT_def", "token_type": "Bearer", "expires_in": 10800,
                                           "username": "loganth"}
    client.post("/api/auth/signup", json={"email": "o@example.com", "password": "correct horse battery"})
    r = client.get("/api/kaggle/oauth/start", params={"returnTo": "/datasets/x/run"}, follow_redirects=False)
    loc = r.headers["location"]
    assert r.status_code == 302 and loc.startswith(f"{server.base}/api/v1/oauth2/authorize?") and "code_challenge_method=S256" in loc
    state = dict(p.split("=", 1) for p in loc.split("?", 1)[1].split("&"))["state"]
    monkeypatch.setattr(kaggle_connect, "_call", lambda path, headers, **kw: {**server.json["/api/v1/oauth2/token"]})
    back = client.get("/api/kaggle/oauth/callback", params={"state": state, "code": "c0de"}, follow_redirects=False)
    assert back.status_code == 302 and back.headers["location"] == "/datasets/x/run?kaggle=connected"
    st = client.get("/api/connections/kaggle").json()
    assert st["connected"] and st["method"] == "Kaggle sign-in" and st["account"] == "loganth"
    replay = client.get("/api/kaggle/oauth/callback", params={"state": state, "code": "c0de"}, follow_redirects=False)
    assert "kaggle=error" in replay.headers["location"]  # states are single-use


# ---------------------------------------------------------------- queue mode (worker)
def test_queue_mode_worker_runs_the_job(client, server, monkeypatch):
    from app import worker

    monkeypatch.setattr(analysis, "RUN_MODE", "queue")
    rid = listed(server, "/files/t.csv", b"a,b\n" + b"1,2\n" * 50, "z.q", "Queued table")
    url = client.get(f"/api/datasets/{rid}/files").json()["files"][0]["url"]
    run_id = client.post(f"/api/datasets/{rid}/analyze", json={"fileUrl": url, "mode": "full"}).json()["runId"]
    assert client.get(f"/api/analyses/{run_id}").json()["status"] == "queued"
    assert worker.run_once("test-worker") and not worker.run_once("test-worker")
    run = client.get(f"/api/analyses/{run_id}").json()
    assert run["status"] == "succeeded" and run["worker"] == "test-worker" and run["report"]["rows_analyzed"] == 50 and "job" not in run


# ---------------------------------------------------------------- fetch speed: ranges, cache, scope (Zenodo ceramics case)
def _ceramics(server, *, ranges=True, etag='"v1"'):
    from .fixtures_formats import ceramics_zip

    data = ceramics_zip()
    path = "/api/records/14607679/files/Supplementary_Data_and_Code.zip/content"
    if not ranges:
        server.no_ranges.add(path)
    server.etags[path] = etag
    rid = listed(server, path, data, "doi.10.5281--zenodo.14605506",
                 "Supplementary data and code for ML prediction of high-entropy ceramics with ultra-high melting points")
    return rid, path, data


def _file_requests(server, path):
    return [r for p, r in server.ranges if p == path]


def test_zip_member_is_read_with_ranges_and_reused(client, server):
    from app.discovery import cache

    cache.clear()
    rid, path, data = _ceramics(server)
    url = client.get(f"/api/datasets/{rid}/files").json()["files"][0]["url"]
    look = client.post(f"/api/datasets/{rid}/inspect", json={"fileUrl": url}).json()
    assert look["rangeReads"] and look["suggested"]["handler"] == "tabular" and look["suggested"]["fullTransfer"] < 30_000
    run = wait(client, client.post(f"/api/datasets/{rid}/analyze", json={"fileUrl": url, "mode": "full"}).json()["runId"])
    assert run["status"] == "succeeded", run["error"]
    rep = run["report"]
    assert rep["fetch"]["cache"] == "range" and rep["transferred_bytes"] < 60_000 and rep["source_bytes"] == len(data) > 9_000_000
    assert rep["scope"] == {"kind": "worksheet", "label": "Full selected worksheet", "file": "Supplementary/1_ML/train_dataset.xlsx",
                            "sheet": "train", "sheets": ["train", "test"]}
    assert rep["rows_analyzed"] == 129 and "range_fetch_ms" in rep["timings"] and "list_ms" in rep["timings"]
    assert "directory from cache" in run["log"]  # Look inside already read the directory
    ins = rep["insights"]
    assert ins["target"]["column"] == "melt_lammps" and ins["target"]["unit"] is None  # no unit in the header: none shown
    assert ins["relationships"]["enough"] and ins["relationships"]["items"][0]["column"] == "VEC_ele_mean"
    assert ins["scatter"]["x"] == "VEC_ele_mean" and ins["scatter"]["y"] == "melt_lammps" and ins["scatter"]["shown"] == 129
    assert ins["numbers"][0]["column"] == "melt_lammps"
    assert any("associated" in f["text"] and "not causes" in f["text"] for f in ins["findings"])
    big = [r for r in _file_requests(server, path) if r and int(r.split("-")[1] or 0) - int(r.split("=")[1].split("-")[0]) > 1_000_000]
    assert not big  # never a large range: only the directory and the workbook
    before = len(_file_requests(server, path))
    again = wait(client, client.post(f"/api/analyses/{run['id']}/retry", json={}).json()["runId"])
    assert again["status"] == "succeeded" and again["report"]["transferred_bytes"] == 0  # member cache: only the 8 KB validation probe
    assert len(_file_requests(server, path)) - before == 1
    sheet = wait(client, client.post(f"/api/datasets/{rid}/analyze", json={"fileUrl": url, "mode": "full", "sheet": "test"}).json()["runId"])
    assert sheet["report"]["scope"]["sheet"] == "test" and sheet["report"]["rows_analyzed"] == 1
    card = client.get(f"/api/datasets/{rid}").json()["analysis"]
    assert card["scope"] == "Full selected worksheet" and card["scopeDetail"]["file"].endswith("train_dataset.xlsx")


def test_provider_without_ranges_streams_once_then_everything_reuses_it(client, server):
    from app.discovery import cache

    cache.clear()
    rid, path, data = _ceramics(server, ranges=False)
    url = client.get(f"/api/datasets/{rid}/files").json()["files"][0]["url"]
    look = client.post(f"/api/datasets/{rid}/inspect", json={"fileUrl": url}).json()
    assert look["fullDownloadRequired"] and "9" in look["note"] and look["members"] is None
    first = wait(client, client.post(f"/api/datasets/{rid}/analyze", json={"fileUrl": url, "mode": "full"}).json()["runId"])
    assert first["status"] == "succeeded" and first["report"]["fetch"]["cache"] == "miss" and first["report"]["transferred_bytes"] == len(data)
    assert "streamed once and cached" in first["log"]
    full_gets = lambda: sum(1 for r in _file_requests(server, path) if r == "")  # noqa: E731
    n = full_gets()
    look = client.post(f"/api/datasets/{rid}/inspect", json={"fileUrl": url}).json()
    assert look["source"] == "cache" and look["memberCount"] == 6 and look["cached"]
    sample = wait(client, client.post(f"/api/datasets/{rid}/analyze", json={"fileUrl": url}).json()["runId"])  # Quick sample: no 422, cached
    assert sample["status"] == "succeeded" and sample["report"]["fetch"]["cache"] == "hit" and sample["report"]["transferred_bytes"] == 0
    assert full_gets() == n  # Look inside and the sample didn't download it again
    server.etags[path] = '"v2"'  # the source changed: the cached copy is no longer valid
    fresh = wait(client, client.post(f"/api/datasets/{rid}/analyze", json={"fileUrl": url, "mode": "full"}).json()["runId"])
    assert fresh["report"]["fetch"]["cache"] == "miss" and full_gets() == n + 1


def test_cancel_during_download_leaves_no_partial_files(client, server):
    from app.discovery import cache

    cache.clear()
    rid, path, data = _ceramics(server, ranges=False)
    server.slow[path] = 0.05
    url = client.get(f"/api/datasets/{rid}/files").json()["files"][0]["url"]
    run_id = client.post(f"/api/datasets/{rid}/analyze", json={"fileUrl": url, "mode": "full"}).json()["runId"]
    for _ in range(100):
        p = client.get(f"/api/analyses/{run_id}").json().get("progress") or {}
        if (p.get("bytes") or 0) > 200_000:
            break
        time.sleep(0.05)
    assert p.get("total") == len(data)  # bytes received and the total, while downloading
    t0 = time.time()
    client.post(f"/api/analyses/{run_id}/cancel")
    run = wait(client, run_id)
    assert run["status"] == "failed" and run["error_kind"] == "cancelled" and time.time() - t0 < 2
    assert not (analysis.RUNS_DIR / run_id).exists()
    assert not [f for f in cache.root().rglob("*") if f.is_file() and not f.name.endswith(".json")]


def test_authenticated_cache_is_scoped_to_the_user():
    from app.discovery import cache

    info = {"etag": '"x"'}
    url = "https://www.kaggle.com/api/v1/datasets/download/o/s"
    assert cache.key(url, info, user="a") != cache.key(url, info, user="b") != cache.key(url, info)
    assert cache.key(url, {"etag": '"y"'}, user="a") != cache.key(url, info, user="a")


def test_saved_report_reopens_lite_and_defers_rows(client):
    rid = add(record("z.lite", "Lite", "Zenodo", "https://example.org/l"))
    run = wait(client, client.post(f"/api/datasets/{rid}/analyze/upload", files={"file": ("t.csv", io.BytesIO(b"a,b\n" + b"1,2\n" * 50), "text/csv")}).json()["runId"])
    lite = client.get(f"/api/analyses/{run['id']}", params={"view": "lite"}).json()
    assert "preview" not in lite["report"] and lite["report"]["preview_deferred"] == 20 and lite["report"]["insights"]
    assert client.get(f"/api/analyses/{run['id']}/details").json()["preview"][0] == [1, 2]
    assert lite["report"]["scope"]["label"] == "Full uploaded file" and "profile_ms" in lite["report"]["timings"]
