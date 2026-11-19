"""Analyze sample / full, bounded downloads and failure handling.

The regression from the recording: Chicago "Traffic Crashes - Crashes" (Socrata, 1M+ rows) used to start a
bulk CSV export and sit at "Downloading". Analyze now reads a 1,000-row SODA sample with a stable order.
"""
import http.server
import threading
import time
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from app import durable
from app.discovery import analysis, fetch, resolve, store
from app.discovery.adapters import http as http_ad
from app.main import app

CHICAGO = "socrata-chicago.85ca-t3if"
SODA_SAMPLE = "https://data.cityofchicago.org/resource/85ca-t3if.csv?$limit=1000&$order=:id"


@pytest.fixture()
def client():
    with TestClient(app) as c:
        store.load_seeds()
        durable.reset_for_tests()
        resolve._CACHE.clear()
        store._invalidate()
        yield c
        durable.reset_for_tests()  # analyses add overlays to seed records; don't leak them into other test modules
        store._invalidate()


def wait(client, run_id, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        run = client.get(f"/api/analyses/{run_id}").json()
        if run["status"] in ("succeeded", "failed"):
            return run
        time.sleep(0.05)
    raise AssertionError("analysis did not finish")


@pytest.fixture()
def chicago(monkeypatch):
    """Socrata metadata + count; downloads served from memory. Records which URLs were fetched."""
    seen = {"downloads": [], "probes": []}

    def get_json(url, headers=None, timeout=None):
        if url == "https://data.cityofchicago.org/api/views/85ca-t3if.json":
            return {"id": "85ca-t3if", "name": "Traffic Crashes - Crashes"}
        if url == "https://data.cityofchicago.org/resource/85ca-t3if.json?$select=count(*)":
            return [{"count": "1123456"}]
        raise http_ad.AdapterError("offline")

    monkeypatch.setattr(resolve, "get_json", get_json)
    monkeypatch.setattr(http_ad, "get_json", get_json)

    def probe(url, expect, timeout=12.0, **kw):
        seen["probes"].append(url)
        return {"bytes_total": None, "content_type": "text/csv", "kind": "text"}

    def download(url, dest, *, max_bytes, deadline, idle, stop_after_lines=None, progress=None, **kw):
        seen["downloads"].append(url)
        if "$offset=" in url:  # emulate a stalled page in a full run
            raise fetch.FetchError("Timed out downloading from data.cityofchicago.org after 412.0 MB.", "timeout")
        rows = ["crash_record_id,crash_date,posted_speed_limit,weather_condition,latitude,longitude,injuries_total"]
        for i in range(1000):
            rows.append(f"id{i},2015-{1 + i % 12:02d}-{1 + i % 28:02d}T08:30:00,{25 + i % 4 * 5},{'CLEAR' if i % 3 else 'RAIN'},"
                        f"{41.7 + i / 10000:.5f},{-87.7 + i / 10000:.5f},{'' if i % 10 == 0 else i % 3}")
        dest.write_text("\n".join(rows) + "\n")
        if progress:
            progress(dest.stat().st_size, None)
        return {"bytes": dest.stat().st_size, "truncated": False, "bytes_total": None}

    monkeypatch.setattr(analysis.fetch_mod, "probe", probe)
    monkeypatch.setattr(analysis.fetch_mod, "download", download)
    return seen


def test_chicago_traffic_crashes_sample_then_reopen_from_curated(client, chicago):
    item = next(i for i in client.get("/api/datasets", params={"q": "traffic crashes chicago"}).json()["items"] if i["id"] == CHICAGO)
    assert not item.get("analysis")
    files = client.get(f"/api/datasets/{CHICAGO}/files").json()
    f = files["files"][0]
    assert files["via"] == "Socrata API" and f["url"].endswith("rows.csv?accessType=DOWNLOAD")

    started = time.time()
    run = wait(client, client.post(f"/api/datasets/{CHICAGO}/analyze", json={"fileUrl": f["url"]}).json()["runId"])
    assert run["status"] == "succeeded", run["error"]
    assert time.time() - started < 10
    assert chicago["downloads"] == [SODA_SAMPLE]  # a bounded SODA query, not the bulk export
    rep = run["report"]
    assert run["mode"] == "sample" and rep["coverage"] == "sample"
    assert rep["rows_analyzed"] == 1000 and rep["rows_total"] == 1123456
    assert "1,000 rows ordered by row id (:id)" in rep["sample_method"] and rep["source_url"] == SODA_SAMPLE
    assert next(c for c in rep["columns"] if c["name"] == "injuries_total")["missing"] == 100
    assert rep["date_coverage"]["column"] == "crash_date"

    # Reopen: same dataset id in Discover and Curated Packs, pointing at this run, after a "refresh" (fresh request).
    store._invalidate()
    cur = client.get("/api/datasets", params={"scope": "curated", "ready": "analyzed"}).json()["items"]
    assert [i["id"] for i in cur] == [CHICAGO]
    a = cur[0]["analysis"]
    assert a["runId"] == run["id"] and a["mode"] == "sample" and a["rowsAnalyzed"] == 1000 and a["rows"] == 1123456
    again = client.get(f"/api/analyses/{a['runId']}").json()
    assert again["isLatest"] and again["report"]["rows_analyzed"] == 1000
    nb = client.get(f"/api/analyses/{run['id']}/notebook").content.decode()
    assert "$limit=1000" in nb  # the notebook reads the same sample, not the 1M-row export


def test_full_analysis_failure_is_recorded_and_keeps_last_good_report(client, chicago):
    url = client.get(f"/api/datasets/{CHICAGO}/files").json()["files"][0]["url"]
    good = wait(client, client.post(f"/api/datasets/{CHICAGO}/analyze", json={"fileUrl": url}).json()["runId"])
    bad = wait(client, client.post(f"/api/datasets/{CHICAGO}/analyze", json={"fileUrl": url, "mode": "full"}).json()["runId"])
    assert bad["status"] == "failed" and bad["error_kind"] == "timeout" and bad["stage"] == "downloading"
    assert "Timed out" in bad["error"] and "Failed while downloading" in bad["log"]
    cur = client.get("/api/datasets", params={"scope": "curated", "ready": "analyzed"}).json()["items"]
    assert [i["id"] for i in cur] == [CHICAGO] and cur[0]["analysis"]["runId"] == good["id"]  # last good report stays
    hist = client.get("/api/analyses", params={"dataset_id": CHICAGO}).json()
    assert [h["status"] for h in hist] == ["failed", "succeeded"] and hist[0]["error_kind"] == "timeout"
    # Retry as a sample: a new run, still one curated entry.
    retry = client.post(f"/api/analyses/{bad['id']}/retry", json={"mode": "sample"})
    assert retry.status_code == 202
    third = wait(client, retry.json()["runId"])
    assert third["status"] == "succeeded" and third["id"] not in (good["id"], bad["id"])
    assert len(durable.query("select id from curated_records where id=?", (CHICAGO,))) == 1


def test_inaccessible_file_is_flagged_before_a_run_starts(client, chicago, monkeypatch):
    url = client.get(f"/api/datasets/{CHICAGO}/files").json()["files"][0]["url"]

    def probe(u, expect, timeout=12.0, **kw):
        raise fetch.FetchError("data.cityofchicago.org answered with a web page instead of the data file (a sign-in page).", "auth")

    monkeypatch.setattr(analysis.fetch_mod, "probe", probe)
    r = client.post(f"/api/datasets/{CHICAGO}/analyze", json={"fileUrl": url})
    assert r.status_code == 422 and r.json()["detail"]["kind"] == "auth"
    assert client.get("/api/analyses").json() == []  # no job, no "Analyzing" screen


# ---------------------------------------------------------------- the real fetch code against a local server
class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        p = self.path
        if p.startswith("/big.csv"):
            self.send_response(200)
            self.send_header("Content-Type", "text/csv")
            self.end_headers()
            self.wfile.write(b"a,b\n")
            for i in range(200_000):
                self.wfile.write(f"{i},{i * 2}\n".encode())
        elif p.startswith("/stall.csv"):
            self.send_response(200)
            self.send_header("Content-Type", "text/csv")
            self.end_headers()
            self.wfile.write(b"a,b\n1,2\n")
            self.wfile.flush()
            time.sleep(3)
        elif p.startswith("/trickle.csv"):
            self.send_response(200)
            self.send_header("Content-Type", "text/csv")
            self.end_headers()
            for i in range(60):
                self.wfile.write(f"{i},x\n".encode())
                self.wfile.flush()
                time.sleep(0.1)
        elif p.startswith("/login.csv"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<!DOCTYPE html><html><title>Sign in</title></html>")
        elif p.startswith("/forbidden.csv"):
            self.send_response(403)
            self.end_headers()
        elif p.startswith("/archive.csv"):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"7z\xbc\xaf\x27\x1c" + b"\x00" * 100)
        else:
            self.send_response(404)
            self.end_headers()


@pytest.fixture(scope="module")
def server():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def test_download_stops_after_sample_rows(server, tmp_path):
    out = tmp_path / "s.csv"
    got = fetch.download(f"{server}/big.csv", out, max_bytes=50 * 2**20, deadline=time.monotonic() + 10, idle=5, stop_after_lines=1001)
    assert got["truncated"] and len(out.read_text().splitlines()) == 1001


def test_download_idle_and_overall_deadlines(server, tmp_path):
    t = time.monotonic()
    with pytest.raises(fetch.FetchError) as e:
        fetch.download(f"{server}/stall.csv", tmp_path / "a.csv", max_bytes=2**20, deadline=time.monotonic() + 30, idle=1)
    assert e.value.kind == "timeout" and time.monotonic() - t < 3
    t = time.monotonic()
    with pytest.raises(fetch.FetchError) as e:
        fetch.download(f"{server}/trickle.csv", tmp_path / "b.csv", max_bytes=2**20, deadline=time.monotonic() + 1.0, idle=5)
    assert e.value.kind == "timeout" and time.monotonic() - t < 2.5


@pytest.mark.parametrize("path,kind", [("/login.csv", "auth"), ("/forbidden.csv", "auth"), ("/archive.csv", "format"), ("/gone.csv", "not_found")])
def test_probe_flags_inaccessible_files(server, path, kind):
    with pytest.raises(fetch.FetchError) as e:
        fetch.probe(server + path, "csv")
    assert e.value.kind == kind


def test_probe_accepts_csv(server):
    assert fetch.probe(f"{server}/big.csv", "csv")["kind"] == "text"


def test_malformed_rows_are_counted_not_silently_dropped(client):
    import io

    csv = "id,light,n\n1,DAYLIGHT,2\n2,DARKNESS, LIGHTED ROAD,3\n3,DUSK,4\n"  # row 2 has an unquoted comma
    r = client.post(f"/api/datasets/{CHICAGO}/analyze/upload", files={"file": ("x.csv", io.BytesIO(csv.encode()), "text/csv")})
    run = wait(client, r.json()["runId"])
    rep = run["report"]
    assert rep["rows_analyzed"] == 2 and rep["rows_skipped"] == 1 and any("too many columns" in r for r in rep["skip_reasons"])


def test_insights_activate_from_fields(client, monkeypatch):
    """NYC-shaped sample: time, hour, borough (with Unknown), coordinates, injuries and plain-language findings."""
    import io

    rows = ["crash_date,crash_time,borough,latitude,longitude,number_of_persons_injured,number_of_persons_killed,collision_id"]
    for i in range(200):
        boro = "" if i % 5 == 0 else ["BROOKLYN", "QUEENS", "BRONX"][i % 3]
        lat, lon = ("", "") if i % 10 == 0 else ("0", "0") if i == 1 else (f"{40.6 + i / 10000:.4f}", f"{-73.9 - i / 10000:.4f}")
        rows.append(f"2013-{1 + i % 12:02d}-0{1 + i % 9},{17 if i % 3 == 0 else i % 24}:30,{boro},{lat},{lon},{i % 3},{int(i == 0)},{100 + i}")
    r = client.post(f"/api/datasets/{CHICAGO}/analyze/upload", files={"file": ("nyc.csv", io.BytesIO("\n".join(rows).encode()), "text/csv")})
    ins = wait(client, r.json()["runId"])["report"]["insights"]
    assert ins["time"]["hour_column"] == "crash_time" and len(ins["time"]["by_hour"]) == 24 and sum(v for _, v in ins["time"]["by_hour"]) == 200
    assert [m for m, _ in ins["time"]["by_month_of_year"]] == list(range(1, 13))
    boro = next(c for c in ins["categories"] if c["column"] == "borough")
    assert boro["unknown"] == 40 and sum(v for _, v in boro["values"]) + boro["other"] + boro["unknown"] == 200
    c = ins["coordinates"]
    assert (c["valid"], c["missing_either"], c["zero_pairs"]) == (179, 20, 1) and c["valid_pct"] == 89.5 and len(c["points"]) == 179
    assert {n["column"] for n in ins["numbers"]} == {"number_of_persons_injured", "number_of_persons_killed"}
    assert sum(v for _, _, v in ins["time"]["weekday_hour"]) == 200
    assert dict(ins["injury_outcomes"]["counts"]) == {"Fatal": 1, "Injury, no fatality": 133, "No injury reported": 66}
    assert any("usable latitude-longitude pair" in f["text"] for f in ins["findings"])
    assert ins["preview"]["values"]


NYC = "socrata-nyc.h9gi-nx95"


@pytest.fixture()
def nyc(monkeypatch):
    seen = {"downloads": [], "probes": [], "short_page": False}

    def get_json(url, headers=None, timeout=None):
        if url == "https://data.cityofnewyork.us/api/views/h9gi-nx95.json":
            return {"id": "h9gi-nx95", "name": "Motor Vehicle Collisions - Crashes",
                    "columns": [{"fieldName": "crash_date", "dataTypeName": "floating_timestamp"}, {"fieldName": "borough", "dataTypeName": "text"}]}
        if url.startswith("https://data.cityofnewyork.us/resource/h9gi-nx95.json?$select=count(*)"):
            return [{"count": "1207" if "where" in url else "2307"}]
        raise http_ad.AdapterError("offline")

    monkeypatch.setattr(resolve, "get_json", get_json)
    monkeypatch.setattr(http_ad, "get_json", get_json)
    def probe(url, expect, timeout=12.0, **kw):
        seen["probes"].append(url)
        return {"bytes_total": None, "content_type": "text/csv", "kind": "text"}

    monkeypatch.setattr(analysis.fetch_mod, "probe", probe)

    def download(url, dest, **kw):
        seen["downloads"].append(url)
        params = parse_qs(urlsplit(url).query)
        offset = int(params.get("$offset", ["0"])[0])
        count = int(params["$limit"][0])
        if seen["short_page"] and offset:
            count -= 1
        # Multiline quoted fields exercise the distinction between lines and rows.
        dest.write_text('crash_date,borough,notes\n' + "".join(
            f'2020-01-0{1 + i % 9}T10:00:00,QUEENS,"row {i}:\n{"x" * 240}"\n' for i in range(offset, offset + count)))
        return {"bytes": dest.stat().st_size, "truncated": False, "bytes_total": None}

    monkeypatch.setattr(analysis.fetch_mod, "download", download)
    return seen


@pytest.mark.parametrize("date_filter,expected", [({}, 2307), ({"dateField": "crash_date", "dateFrom": "2020-01-01"}, 1207)])
def test_full_uses_every_socrata_page_above_direct_import_limit(client, nyc, monkeypatch, date_filter, expected):
    monkeypatch.setattr(analysis, "MAX_BYTES", 100)
    monkeypatch.setattr(analysis, "SODA_PAGE_ROWS", 500)
    url = client.get(f"/api/datasets/{NYC}/files").json()["files"][0]["url"]
    r = client.post(f"/api/datasets/{NYC}/analyze", json={"fileUrl": url, "mode": "full", **date_filter})
    assert r.status_code == 202
    run = wait(client, r.json()["runId"])
    assert run["status"] == "succeeded", run["error"]
    rep = run["report"]
    assert rep["coverage"] == "full" and rep["paged_source"]
    assert rep["rows_analyzed"] == rep["rows_total"] == expected
    assert run["file_bytes"] > analysis.MAX_BYTES and rep["duplicate_rows"] == 0
    assert run["progress"]["rows"] == expected
    assert not any("rows.csv" in u for u in nyc["probes"] + nyc["downloads"])
    assert [int(parse_qs(urlsplit(u).query)["$offset"][0]) for u in nyc["downloads"]] == list(range(0, expected, 500))
    assert all(("$where=" in u) == bool(date_filter) for u in nyc["downloads"])
    nb = client.get(f"/api/analyses/{run['id']}/notebook").content.decode()
    assert "$offset={offset}" in nb


def test_short_page_never_publishes_a_full_report(client, nyc, monkeypatch):
    monkeypatch.setattr(analysis, "SODA_PAGE_ROWS", 500)
    nyc["short_page"] = True
    url = client.get(f"/api/datasets/{NYC}/files").json()["files"][0]["url"]
    r = client.post(f"/api/datasets/{NYC}/analyze", json={"fileUrl": url, "mode": "full"})
    run = wait(client, r.json()["runId"])
    assert run["status"] == "failed" and run["error_kind"] == "network"
    assert run["report"] is None
    assert not client.get(f"/api/datasets/{NYC}").json().get("analysis")


def test_failed_full_run_keeps_the_sample_report_and_cleans_up(client, nyc, monkeypatch):
    """The source grows mid-run: the full run fails as temporary (Retry), the sample stays latest, staged pages are deleted."""
    monkeypatch.setattr(analysis, "SODA_PAGE_ROWS", 500)
    url = client.get(f"/api/datasets/{NYC}/files").json()["files"][0]["url"]
    sample = wait(client, client.post(f"/api/datasets/{NYC}/analyze", json={"fileUrl": url}).json()["runId"])
    assert sample["status"] == "succeeded"
    real, calls = analysis._socrata_count, []

    def growing(plan, timeout=None):
        calls.append(1)
        n = real(plan, timeout)
        return n + 3 if len(calls) >= 3 else n  # preflight, run start: 2307; after the last page: 2310

    monkeypatch.setattr(analysis, "_socrata_count", growing)
    full = wait(client, client.post(f"/api/datasets/{NYC}/analyze", json={"fileUrl": url, "mode": "full"}).json()["runId"])
    assert full["status"] == "failed" and full["error_kind"] == "network" and full["report"] is None
    assert "2,307 rows at the start, 2,310 at the end" in full["error"]
    assert full["progress"]["rows"] == full["progress"]["row_total"] == 2307
    assert not (analysis.RUNS_DIR / full["id"]).exists()
    assert client.get(f"/api/datasets/{NYC}").json()["analysis"]["runId"] == sample["id"]


def test_paged_full_run_is_refused_without_a_row_count(client, nyc, monkeypatch):
    monkeypatch.setattr(analysis, "_socrata_count", lambda plan, timeout=None: None)
    url = client.get(f"/api/datasets/{NYC}/files").json()["files"][0]["url"]
    r = client.post(f"/api/datasets/{NYC}/analyze", json={"fileUrl": url, "mode": "full"})
    assert r.status_code == 422 and r.json()["detail"]["kind"] == "network"
    assert client.get("/api/analyses").json() == []


def test_date_range_sample_uses_soql_where(client, nyc):
    url = client.get(f"/api/datasets/{NYC}/files").json()["files"][0]["url"]
    run = wait(client, client.post(f"/api/datasets/{NYC}/analyze", json={
        "fileUrl": url, "mode": "sample", "dateField": "crash_date", "dateFrom": "2020-01-01", "dateTo": "2020-12-31"}).json()["runId"])
    assert run["status"] == "succeeded", run["error"]
    sample_url = nyc["downloads"][-1]
    assert "$where=crash_date%20between%20%272020-01-01T00%3A00%3A00%27" in sample_url and "$limit=1000" in sample_url
    rep = run["report"]
    assert rep["rows_total"] == 1207 and "between 2020-01-01 and 2020-12-31" in rep["sample_method"]
    assert run["params"] == {"dateField": "crash_date", "dateFrom": "2020-01-01", "dateTo": "2020-12-31"}
    bad = client.post(f"/api/datasets/{NYC}/analyze", json={"fileUrl": url, "dateField": "x; drop", "dateFrom": "2020-01-01"})
    assert bad.status_code == 422


def test_netcdf_entry_reports_format_limitation(client, monkeypatch):
    rec = store.all_records()["nasa-cmr.c2723754864-ges_disc"]
    assert any("netcdf" in str(v).lower() for v in rec["formats"]["values"])
    monkeypatch.setattr(resolve, "resolve", lambda r, refresh=False: {"files": [], "total": 0, "via": None, "signInRequired": False, "note": None, "errors": []})
    res = client.get("/api/datasets/nasa-cmr.c2723754864-ges_disc/files").json()
    assert res["unsupportedFormats"] == ["NetCDF"]
    item = client.get(f"/api/datasets/{rec['id']}").json()
    assert item["runnable"] == "unsupported" and item["unsupportedFormats"] == ["NetCDF"]


def test_household_power_trends_and_card_preview(client):
    import io

    rows = ["Date;Time;Global_active_power;Global_reactive_power;Voltage"]
    for i in range(600):
        h, m = divmod(17 * 60 + 24 + i, 60)
        rows.append(f"{16 + h // 24}/12/2006;{h % 24:02d}:{m:02d}:00;{'?' if i % 100 == 0 else f"{1 + (i % 7) / 3:.3f}"};0.1{i % 9};{233 + (i % 11) / 2:.3f}")
    r = client.post("/api/datasets/uci.235/analyze/upload", files={"file": ("household_power_consumption.txt", io.BytesIO("\n".join(rows).encode()), "text/plain")})
    run = wait(client, r.json()["runId"])
    ins = run["report"]["insights"]
    cols = {c["name"]: c for c in run["report"]["columns"]}
    assert cols["Global_active_power"]["kind"] == "numeric" and cols["Global_active_power"]["missing"] == 6  # '?' read as missing
    assert ins["trends"]["series"][0]["column"] == "Voltage" and ins["trends"]["by_hour"]["column"] == "Global_active_power"
    assert "weekday_hour" not in ins["time"]  # regular minute readings: no event heatmap
    card = next(i for i in client.get("/api/datasets", params={"scope": "curated", "ready": "analyzed"}).json()["items"] if i["id"] == "uci.235")
    assert card["analysis"]["preview"]["label"].startswith("Voltage over time") and len(card["analysis"]["preview"]["values"]) >= 3


def test_cancel_stops_a_run(client, chicago, monkeypatch):
    url = client.get(f"/api/datasets/{CHICAGO}/files").json()["files"][0]["url"]
    gate = threading.Event()
    real = analysis.fetch_mod.download

    def slow(u, dest, **kw):
        gate.wait(5)
        kw["progress"](1, None)  # the first progress callback sees the cancel flag
        return real(u, dest, **kw)

    monkeypatch.setattr(analysis.fetch_mod, "download", slow)
    rid = client.post(f"/api/datasets/{CHICAGO}/analyze", json={"fileUrl": url}).json()["runId"]
    client.post(f"/api/analyses/{rid}/cancel")
    gate.set()
    run = wait(client, rid)
    assert run["status"] == "failed" and run["error_kind"] == "cancelled"
