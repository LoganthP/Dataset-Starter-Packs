"""Release test for live discovery: empty local index -> 'Social media datasets' -> external cards,
requirement checks, preview, import, outages and arbitrary topics. Provider payloads mirror the real APIs."""
import io
import os
import shutil
from pathlib import Path

import pytest

STATE = Path(__file__).parent / ".state-live"
shutil.rmtree(STATE, ignore_errors=True)
os.environ["DSP_STATE_DIR"] = str(STATE)
os.environ.setdefault("BRAVE_SEARCH_API_KEY", "test-key")

from fastapi.testclient import TestClient  # noqa: E402

from app import durable  # noqa: E402
from app.discovery import store  # noqa: E402
from app.discovery.adapters import cmr, datacite, huggingface, kaggle, uci, web  # noqa: E402
from app.discovery.adapters.http import AdapterError  # noqa: E402
from app.main import app  # noqa: E402

TWEET_EVAL = {
    "id": "cardiffnlp/tweet_eval", "author": "cardiffnlp", "gated": False, "private": False, "disabled": False,
    "lastModified": "2024-01-04T16:40:33.000Z",
    "description": "TweetEval consists of seven heterogenous tasks in Twitter, all framed as multi-class tweet classification.",
    "tags": ["task_categories:text-classification", "task_ids:sentiment-classification", "language:en", "license:unknown", "format:parquet", "modality:text"],
    "cardData": {"license": ["unknown"], "task_categories": ["text-classification"], "pretty_name": "TweetEval",
                 "dataset_info": [
                     {"config_name": "sentiment", "features": [{"name": "text", "dtype": "string"},
                                                               {"name": "label", "dtype": {"class_label": {"names": {"0": "negative", "1": "neutral", "2": "positive"}}}}],
                      "splits": [{"name": "train", "num_examples": 45615}, {"name": "test", "num_examples": 12284}, {"name": "validation", "num_examples": 2000}]},
                     {"config_name": "emotion", "features": [{"name": "text", "dtype": "string"},
                                                             {"name": "label", "dtype": {"class_label": {"names": {"0": "anger", "1": "joy"}}}}]}]},
}
HF_SOCIAL = {"id": "someone/social-posts-2023", "author": "someone", "tags": ["format:csv", "modality:text"], "description": "Posts with timestamps.",
             "cardData": {"license": "cc-by-4.0", "dataset_info": {"features": [{"name": "text", "dtype": "string"},
                                                                                  {"name": "created_at", "dtype": "timestamp[s]"}]}}}
SENTIMENT140 = {"ref": "kazanova/sentiment140", "title": "Sentiment140 dataset with 1.6 million tweets", "subtitle": "Sentiment analysis with tweets",
                "ownerName": "KazAnova", "licenseName": "Other (specified in description)", "totalBytes": 84855679,
                "lastUpdated": "2017-09-13T22:43:19.117Z", "tags": [{"name": "social networks"}]}
FIGSHARE = {"id": "10.6084/m9.figshare.35050510.v1", "attributes": {
    "doi": "10.6084/m9.figshare.35050510.v1", "titles": [{"title": "Flood-season social media counts and post-level emotion predictions, Wuhan 2010-2025"}],
    "descriptions": [{"description": "Daily panel of 1,754 days and 12,794 Weibo posts."}], "publisher": "figshare", "publicationYear": 2026,
    "url": "https://figshare.com/articles/dataset/x/35050510/1", "rightsList": [{"rights": "Creative Commons Attribution 4.0 International", "rightsUri": "https://creativecommons.org/licenses/by/4.0/legalcode"}],
    "formats": [], "sizes": ["825197 Bytes"], "dates": [{"date": "2010-01-01/2025-12-31", "dateType": "Collected"}], "subjects": [{"subject": "Natural language processing"}]}}
BRAVE = {"web": {"results": [
    {"title": "SNAP: Social network: Reddit Hyperlink Network", "url": "https://snap.stanford.edu/data/soc-RedditHyperlinks.html",
     "description": "The hyperlink network represents the directed connections between two subreddits."},
    {"title": "10 social media datasets you should know", "url": "https://medium.com/@x/10-social-media-datasets", "description": "Blog"},
    {"title": "cardiffnlp/tweet_eval · Datasets at Hugging Face", "url": "https://huggingface.co/datasets/cardiffnlp/tweet_eval", "description": "TweetEval"},
    {"title": "Twitter Sentiment Corpus", "url": "https://example.edu/data/twitter-corpus", "description": "A corpus of tweets."},
]}}


class Fake:
    """Routes adapter HTTP calls to canned payloads; providers can be switched to fail."""
    def __init__(self):
        self.down: set[str] = set()
        self.calls: list[str] = []

    def __call__(self, url, headers=None, timeout=None):
        self.calls.append(url)
        for key in self.down:
            if key in url:
                raise AdapterError("TimeoutError: timed out")
        if "huggingface.co/api/datasets" in url:
            if "volcano" in url:
                return [{"id": "geo/volcano-eruptions", "author": "geo", "tags": ["format:csv"], "description": "Eruptions since 1900.",
                         "cardData": {"license": "cc0-1.0", "dataset_info": {"features": [{"name": "eruption_date", "dtype": "date32"},
                                                                                          {"name": "latitude", "dtype": "float64"}, {"name": "longitude", "dtype": "float64"}]}}}]
            return [TWEET_EVAL, HF_SOCIAL] if "social" in url else []
        if "datasets-server.huggingface.co/splits" in url:
            return {"splits": [{"dataset": "cardiffnlp/tweet_eval", "config": "sentiment", "split": "train"}]}
        if "datasets-server.huggingface.co/parquet" in url:
            return {"parquet_files": [{"dataset": "cardiffnlp/tweet_eval", "config": "sentiment", "split": "train", "size": 2048,
                                       "url": "https://huggingface.co/datasets/cardiffnlp/tweet_eval/resolve/refs%2Fconvert%2Fparquet/sentiment/train/0000.parquet",
                                       "filename": "0000.parquet"}]}
        if "datasets-server.huggingface.co/first-rows" in url:
            return {"features": [{"name": "text", "type": {"dtype": "string", "_type": "Value"}},
                                 {"name": "label", "type": {"names": ["negative", "neutral", "positive"], "_type": "ClassLabel"}}],
                    "rows": [{"row": {"text": "great day", "label": 2}}, {"row": {"text": "meh", "label": 1}}]}
        if "kaggle.com/api/v1/datasets/list" in url:
            return [SENTIMENT140] if "social" in url else []
        if "api.datacite.org" in url:
            return {"data": [FIGSHARE] if "social" in url else []}
        if "api.search.brave.com" in url:
            return BRAVE if "social" in url else {"web": {"results": []}}
        if "archive.ics.uci.edu/api/datasets/list" in url:
            return {"status": 200, "data": []}
        if "cmr.earthdata.nasa.gov" in url:
            return {"items": []}
        raise AdapterError(f"unexpected URL {url}")


@pytest.fixture()
def fake(monkeypatch, tmp_path):
    f = Fake()
    for mod in (huggingface, kaggle, datacite, web, uci, cmr):
        monkeypatch.setattr(mod, "get_json", f)
    monkeypatch.setattr(web, "enrich", lambda rec: rec)  # page fetching is tested separately
    # Start from an EMPTY local index: no catalog records and no packs.
    monkeypatch.setattr(store, "RECORDS_DIR", tmp_path / "no-records")
    monkeypatch.setattr(store.config, "PACKS_DIR", tmp_path / "no-packs")
    with store.connect() as con:
        con.executescript(store.SCHEMA)
        for t in ("records", "records_fts", "live_hits", "live_runs"):
            con.execute(f"delete from {t}")
    durable.reset_for_tests()
    store.load_seeds()
    store._invalidate()
    return f


@pytest.fixture()
def client(fake):
    with TestClient(app) as c:
        # TestClient startup reloads seeds - still empty because of the patches above.
        yield c


def run_all(client, q):
    return {p["key"]: client.get("/api/live/search", params={"provider": p["key"], "q": q}).json() for p in client.get("/api/live/providers").json()}


def test_empty_catalog_is_reported_not_hidden(client):
    meta = client.get("/api/discover/meta").json()
    assert meta["total"] == 0
    assert meta["catalogHealth"]["recordsDirExists"] is False
    assert any("Catalog folder not found" in e for e in meta["catalogHealth"]["errors"])


def test_social_media_from_empty_index(client, fake):
    q = "Social media datasets"
    statuses = run_all(client, q)
    assert statuses["huggingface"]["status"] == "ok" and statuses["web"]["status"] == "ok"
    res = client.get("/api/datasets", params={"q": q, "include_failed": "1", "page_size": "50"}).json()
    ids = [i["id"] for i in res["items"]]
    assert "hf.cardiffnlp--tweet_eval" in ids and "kaggle.kazanova-sentiment140" in ids
    assert any(i.startswith("doi.") for i in ids)
    assert any(i["provider"] == "snap.stanford.edu" for i in res["items"])
    assert not any("medium.com" in i["canonicalUrl"] for i in res["items"])     # blogs dropped
    assert ids.count("hf.cardiffnlp--tweet_eval") == 1                           # web hit merged into the HF record
    tweet = next(i for i in res["items"] if i["id"] == "hf.cardiffnlp--tweet_eval")
    assert tweet["liveHit"]["provider"] in ("huggingface", "web") and tweet["origin"] == "live"
    assert tweet["schemaStatus"] == "complete" and set(tweet["configs"]) == {"sentiment", "emotion"}


def test_timestamp_required_sorts_social_results(client):
    q = "Social media datasets"
    run_all(client, q)
    res = client.get("/api/datasets", params={"q": q, "fields": "timestamp", "include_failed": "1", "page_size": "50"}).json()
    fit = {i["id"]: i for i in res["items"]}
    assert fit["hf.cardiffnlp--tweet_eval"]["fit"] == "does-not-meet"            # documented schema has no time field
    assert fit["kaggle.kazanova-sentiment140"]["fit"] == "needs-verification"    # schema not documented in search results
    assert fit["hf.someone--social-posts-2023"]["fit"] == "meets"                 # typed timestamp[s] column on the card
    assert "created_at" in fit["hf.someone--social-posts-2023"]["reasons"][0]["text"]


def test_provider_outage_gives_partial_results(client, fake):
    fake.down.add("api.datacite.org")
    statuses = run_all(client, "social media")
    assert statuses["datacite"]["status"] == "error" and "Timeout" in statuses["datacite"]["detail"]
    assert statuses["huggingface"]["status"] == "ok"
    res = client.get("/api/datasets", params={"q": "social media", "page_size": "50"}).json()
    assert "hf.cardiffnlp--tweet_eval" in [i["id"] for i in res["items"]]


def patch_fetch(monkeypatch, fake_download):
    """Replace network access for Analyze: the probe passes and downloads come from `fake_download(url, dest)`."""
    from app.discovery import analysis

    monkeypatch.setattr(analysis.fetch_mod, "probe", lambda url, expect, timeout=12.0, **kw: {"bytes_total": None, "content_type": "", "kind": "text"})

    def download(url, dest, **kw):
        return {"bytes": fake_download(url, dest), "truncated": False, "bytes_total": None}

    monkeypatch.setattr(analysis.fetch_mod, "download", download)


def wait_analysis(client, run_id, timeout=30):
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        run = client.get(f"/api/analyses/{run_id}").json()
        if run["status"] in ("succeeded", "failed"):
            return run
        time.sleep(0.05)
    raise AssertionError(f"analysis {run_id} did not finish")


def test_results_are_cached_per_query(client, fake):
    first = client.get("/api/live/search", params={"provider": "huggingface", "q": "social media"}).json()
    calls = len(fake.calls)
    second = client.get("/api/live/search", params={"provider": "huggingface", "q": "Social media datasets"}).json()
    assert first["status"] == "ok" and second["status"] == "cached" and len(fake.calls) == calls
    fresh = client.get("/api/live/search", params={"provider": "huggingface", "q": "social media", "refresh": "true"}).json()
    assert fresh["status"] == "ok" and len(fake.calls) > calls


def test_web_search_not_configured_is_explicit(client, monkeypatch):
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
    r = client.get("/api/live/search", params={"provider": "web", "q": "social media"}).json()
    assert r["status"] == "not-configured" and "BRAVE_SEARCH_API_KEY" in r["detail"]


def test_preview_and_import_verify_coverage(client):
    run_all(client, "social media")
    prev = client.get("/api/datasets/hf.cardiffnlp--tweet_eval/preview").json()
    assert [c["name"] for c in prev["columns"]] == ["text", "label"] and prev["rows"][0] == ["great day", 2]
    # Sentiment140 needs a Kaggle sign-in: the user downloads it and uploads it here.
    csv = "target,ids,date,flag,user,text\n0,1,2009-04-06 22:19:45,NO_QUERY,a,hello\n4,2,2009-06-25 10:28:31,NO_QUERY,b,bye\n"
    up = client.post("/api/datasets/kaggle.kazanova-sentiment140/analyze/upload",
                     files={"file": ("sentiment140.csv", io.BytesIO(csv.encode()), "text/csv")})
    assert up.status_code == 202, up.text
    run = wait_analysis(client, up.json()["runId"])
    assert run["status"] == "succeeded", run
    rep = run["report"]
    assert rep["coverage"] == "full" and rep["rows_total"] == 2 and rep["duplicate_rows"] == 0
    date_col = next(c for c in rep["columns"] if c["name"] == "date")
    assert "timestamp" in date_col["concepts"] and date_col["min"].startswith("2009-04-06")
    assert run["source"]["provider"] == "Kaggle" and run["file_sha256"] and run["isLatest"]
    d = client.get("/api/datasets/kaggle.kazanova-sentiment140", params={"fields": "timestamp", "min_years": "1"}).json()
    by = {r["key"]: r for r in d["reasons"]}
    assert by["field:timestamp"]["outcome"] == "met" and "verified" in by["field:timestamp"]["text"]
    assert by["min_years"]["outcome"] == "failed"  # the uploaded sample spans < 1 year, measured from the file
    assert d["analysis"]["runId"] == run["id"]
    # Analyzed datasets join Curated Packs, under the same id, with an Analyzed badge.
    cur = client.get("/api/datasets", params={"scope": "curated"}).json()
    item = next(i for i in cur["items"] if i["id"] == "kaggle.kazanova-sentiment140")
    assert item["analysis"]["runId"] == run["id"] and "analyzed" in item["readiness"]
    only = client.get("/api/datasets", params={"scope": "curated", "ready": "analyzed"}).json()
    assert [i["id"] for i in only["items"]] == ["kaggle.kazanova-sentiment140"]
    hist = client.get("/api/analyses", params={"dataset_id": "kaggle.kazanova-sentiment140"}).json()
    assert hist[0]["id"] == run["id"] and hist[0]["rows"] == 2
    nb = client.get(f"/api/analyses/{run['id']}/notebook")
    assert nb.status_code == 200 and b"read_csv" in nb.content


def test_comparison_snapshot_is_immutable(client):
    run_all(client, "social media")
    ids = ["kaggle.kazanova-sentiment140", "hf.cardiffnlp--tweet_eval"]
    csv = "date,text\n2009-04-06,a\n2009-04-07,b\n"
    first = wait_analysis(client, client.post(f"/api/datasets/{ids[0]}/analyze/upload",
                                              files={"file": ("a.csv", io.BytesIO(csv.encode()), "text/csv")}).json()["runId"])
    cur = client.get("/api/comparisons/current", params={"ids": ",".join(ids), "criteria": "fields=timestamp"}).json()["items"]
    assert cur[0]["analysis"]["runId"] == first["id"] and cur[1]["analysis"] is None  # "Analysis pending"
    saved = client.post("/api/comparisons", json={"ids": ids, "criteria": "fields=timestamp"}).json()
    assert saved["analysis_run_ids"] == {ids[0]: first["id"], ids[1]: None}
    # Re-analysis creates a new run and updates the latest report, but not the saved comparison.
    second = wait_analysis(client, client.post(f"/api/datasets/{ids[0]}/analyze/upload",
                                               files={"file": ("b.csv", io.BytesIO((csv + "2010-01-01,c\n").encode()), "text/csv")}).json()["runId"])
    assert second["id"] != first["id"]
    again = client.get(f"/api/comparisons/{saved['id']}").json()
    assert again["snapshot"][0]["analysis"]["runId"] == first["id"] and again["snapshot"][0]["analysis"]["rowsTotal"] == 2
    latest = client.get("/api/comparisons/current", params={"ids": ids[0]}).json()["items"][0]
    assert latest["analysis"]["runId"] == second["id"] and latest["analysis"]["rowsTotal"] == 3
    listed = client.get("/api/comparisons").json()
    assert listed[0]["id"] == saved["id"] and len(listed[0]["dataset_titles"]) == 2
    assert client.get(f"/api/analyses/{first['id']}").json()["isLatest"] is False


def test_analyze_listed_parquet_file(client, monkeypatch):
    import duckdb


    def fake_download(url, dest):
        assert url.endswith("0000.parquet")
        duckdb.sql("select * from (values ('a', 0, date '2020-01-01'), ('b', 1, date '2020-06-01'), ('b', 1, date '2020-06-01')) "
                   "t(text, label, created)").write_parquet(str(dest))
        return dest.stat().st_size

    patch_fetch(monkeypatch, fake_download)
    run_all(client, "social media")
    files = client.get("/api/datasets/hf.cardiffnlp--tweet_eval/files").json()
    assert files["files"][0]["format"] == "parquet"
    run = wait_analysis(client, client.post("/api/datasets/hf.cardiffnlp--tweet_eval/analyze", json={"fileIndex": 0}).json()["runId"])
    assert run["status"] == "succeeded", run["error"]
    rep = run["report"]
    assert rep["rows_total"] == 3 and rep["duplicate_rows"] == 1 and rep["date_coverage"]["min"] == "2020-01-01"
    assert run["file_url"].endswith("0000.parquet") and run["source"]["canonicalUrl"].startswith("https://huggingface.co/")
    item = next(i for i in client.get("/api/datasets", params={"q": "social media"}).json()["items"] if i["id"] == "hf.cardiffnlp--tweet_eval")
    assert item["analysis"]["runId"] == run["id"] and item["analyzable"]


def test_documentation_records_are_labelled():
    from app.discovery.adapters import web as webad

    rec = webad.normalize({"title": "ESA mission data guide", "url": "https://esa.int/docs/guide.pdf", "snippet": ""})
    assert rec["kind"] == "documentation"


def test_bad_upload_fails_cleanly(client):
    run_all(client, "social media")
    r = client.post("/api/datasets/hf.cardiffnlp--tweet_eval/analyze/upload", files={"file": ("x.exe", io.BytesIO(b"MZ\x00\x90"), "application/octet-stream")})
    odd = wait_analysis(client, r.json()["runId"])  # unknown types get an inspection-only report, not an error
    assert odd["status"] == "succeeded" and odd["report"]["kind"] == "inspection" and odd["report"]["inspection"]["detected"] == "binary"
    bad = wait_analysis(client, client.post("/api/datasets/hf.cardiffnlp--tweet_eval/analyze/upload",
                                            files={"file": ("x.parquet", io.BytesIO(b"not parquet"), "application/octet-stream")}).json()["runId"])
    assert bad["status"] == "failed" and bad["error"]


def test_arbitrary_topic_works(client):
    run_all(client, "volcano eruptions with coordinates")
    res = client.get("/api/datasets", params={"q": "volcano eruptions with coordinates", "fields": "latlon,timestamp"}).json()
    assert res["items"] and res["items"][0]["id"] == "hf.geo--volcano-eruptions" and res["items"][0]["fit"] == "meets"


def test_web_enrichment_reads_schema_org(monkeypatch):
    page = """<html><head><meta name="description" content="Corpus page">
    <script type="application/ld+json">{"@type": "Dataset", "description": "Tweets 2015-2016", "license": "https://creativecommons.org/licenses/by/4.0/",
     "temporalCoverage": "2015-01-01/2016-12-31", "distribution": [{"@type": "DataDownload", "encodingFormat": "text/csv", "contentUrl": "https://example.edu/t.csv"}],
     "variableMeasured": [{"name": "created_at"}, {"name": "text"}]}</script></head></html>"""
    monkeypatch.setattr(web, "_fetch_html", lambda url, limit=0: page)
    rec = web.enrich(web.normalize({"title": "Twitter corpus", "url": "https://example.edu/data/twitter-corpus", "snippet": ""}))
    assert rec["coverage"]["temporal"]["start"] == "2015-01-01" and rec["license"]["commercialUse"] == "allowed"
    assert rec["files"][0]["format"] == "csv" and rec["fields"][0]["concepts"] == ["timestamp"]


# ---------------------------------------------------------------- Analyze: resolving provider files
ZENODO_DOI = {"id": "10.5281/zenodo.13831", "attributes": {
    "doi": "10.5281/zenodo.13831", "titles": [{"title": "Road Traffic Crash Incidents in Nigeria (2015-2024)"}],
    "descriptions": [{"description": "AI-ready dataset of road traffic crash incidents extracted from news reports."}],
    "publisher": "Zenodo", "publicationYear": 2024, "url": "https://zenodo.org/doi/10.5281/zenodo.13831",
    "types": {"resourceTypeGeneral": "Dataset"}, "formats": [], "rightsList": [{"rights": "Creative Commons Attribution Non Commercial Share Alike 4.0 International"}],
    "dates": [], "subjects": []}}
ZENODO_RECORD = {"id": 13831, "files": [
    {"key": "rtc_incidents.csv", "size": 412_000, "links": {"self": "https://zenodo.org/api/records/13831/files/rtc_incidents.csv/content"}},
    {"key": "codebook.pdf", "size": 90_000, "links": {"self": "https://zenodo.org/api/records/13831/files/codebook.pdf/content"}}]}


def _traffic_fake(fake, extra=None):
    routes = {"api.datacite.org": {"data": [ZENODO_DOI]}, "zenodo.org/api/records/13831": ZENODO_RECORD, **(extra or {})}

    def f(url, headers=None, timeout=None):
        for k, v in routes.items():
            if k in url:
                return v
        if "huggingface.co/api/datasets" in url or "kaggle.com" in url:
            return []
        if "brave" in url or "googleapis" in url:
            return {"web": {"results": []}}
        return fake(url, headers, timeout)
    return f


@pytest.fixture()
def traffic(fake, monkeypatch):
    from app.discovery import resolve as res

    f = _traffic_fake(fake)
    for mod in (huggingface, kaggle, datacite, web, uci, cmr, res):
        monkeypatch.setattr(mod, "get_json", f)
    res._CACHE.clear()
    return f


def test_format_unknown_result_resolves_files_and_analyzes(client, traffic, monkeypatch):

    def fake_download(url, dest):
        assert url.endswith("rtc_incidents.csv/content")
        dest.write_text("date,state,lat,lon,casualties\n2016-01-03,Lagos,6.5,3.4,2\n2023-12-30,Kano,12.0,8.5,5\n2020-05-01,Oyo,7.4,3.9,\n")
        return dest.stat().st_size

    patch_fetch(monkeypatch, fake_download)
    client.get("/api/live/search", params={"provider": "datacite", "q": "traffic incidents"})
    item = next(i for i in client.get("/api/datasets", params={"q": "traffic incidents"}).json()["items"] if "Nigeria" in i["title"])
    assert item["formats"]["values"] == [] and item["provider"] == "Zenodo"
    assert item["analyzable"]  # Analyze is offered even though the search result says "Format unknown"
    files = client.get(f"/api/datasets/{item['id']}/files").json()
    assert files["via"] == "Zenodo API"
    assert [(f["name"], f["format"], f["supported"]) for f in files["files"]] == [("rtc_incidents.csv", "csv", True), ("codebook.pdf", "pdf", False)]
    bad = client.post(f"/api/datasets/{item['id']}/analyze", json={"fileUrl": files["files"][1]["url"]})
    assert bad.status_code == 422 and "PDF" in bad.json()["detail"]["message"] and bad.json()["detail"]["kind"] == "format"
    other = client.post(f"/api/datasets/{item['id']}/analyze", json={"fileUrl": "https://evil.example/x.csv"})
    assert other.status_code == 422  # only files the provider lists
    run = wait_analysis(client, client.post(f"/api/datasets/{item['id']}/analyze", json={"fileUrl": files["files"][0]["url"]}).json()["runId"])
    assert run["status"] == "succeeded", run["error"]
    rep = run["report"]
    assert rep["rows_total"] == 3 and rep["date_coverage"]["min"].startswith("2016-01-03")
    assert next(c for c in rep["columns"] if c["name"] == "casualties")["missing"] == 1
    # The same id now carries the analysis on Discover and in Curated Packs.
    again = next(i for i in client.get("/api/datasets", params={"q": "traffic incidents"}).json()["items"] if i["id"] == item["id"])
    assert again["analysis"]["runId"] == run["id"] and again["formats"]["values"] == ["csv"]
    cur = client.get("/api/datasets", params={"scope": "curated", "ready": "analyzed"}).json()["items"]
    assert [i["id"] for i in cur] == [item["id"]]


def test_analyzed_record_survives_losing_the_live_cache(client, traffic, monkeypatch):
    """A new container / serverless cold start has an empty live cache; the curated record comes from durable storage."""

    patch_fetch(monkeypatch, lambda url, dest: dest.write_text("a,b\n1,2\n") and dest.stat().st_size)
    client.get("/api/live/search", params={"provider": "datacite", "q": "traffic incidents"})
    rid = next(i["id"] for i in client.get("/api/datasets", params={"q": "traffic incidents"}).json()["items"] if "Nigeria" in i["title"])
    url = client.get(f"/api/datasets/{rid}/files").json()["files"][0]["url"]
    run = wait_analysis(client, client.post(f"/api/datasets/{rid}/analyze", json={"fileUrl": url}).json()["runId"])
    with store.connect() as con:
        for t in ("records", "records_fts", "live_hits", "live_runs"):
            con.execute(f"delete from {t}")
    store._invalidate()
    cur = client.get("/api/datasets", params={"scope": "curated"}).json()["items"]
    assert [i["id"] for i in cur] == [rid] and cur[0]["analysis"]["runId"] == run["id"]
    assert client.get(f"/api/datasets/{rid}").json()["title"].startswith("Road Traffic Crash")


def test_resolvers_for_common_repositories(monkeypatch):
    from app.discovery import resolve as res

    pages = {
        "https://api.figshare.com/v2/articles/777/files": [{"name": "crashes.parquet", "size": 10, "download_url": "https://ndownloader.figshare.com/files/1"}],
        "https://data.cityofnewyork.us/api/views/h9gi-nx95.json": {"id": "h9gi-nx95", "name": "Motor Vehicle Collisions - Crashes"},
        "https://catalog.data.gov/api/3/action/package_show?id=road-incidents": {"success": True, "result": {"resources": [
            {"url": "https://example.gov/incidents.csv", "format": "CSV", "name": "Incidents"}, {"url": "https://example.gov/api", "format": "API", "name": "API"}]}},
        "https://dataverse.harvard.edu/api/datasets/:persistentId/?persistentId=doi:10.7910/DVN/ABC": {"data": {"latestVersion": {"files": [
            {"dataFile": {"id": 42, "filename": "accidents.tab", "originalFileName": "accidents.csv", "originalFileFormat": "text/csv", "filesize": 99}}]}}},
    }
    monkeypatch.setattr(res, "get_json", lambda url, headers=None, timeout=None: pages[url] if url in pages else (_ for _ in ()).throw(AdapterError("404")))
    html_page = ('<script type="application/ld+json">{"@type":"Dataset","distribution":[{"contentUrl":"https://cdn.example.org/a.csv",'
                 '"encodingFormat":"text/csv"}]}</script><a href="/files/b.parquet">b</a>')
    monkeypatch.setattr(res, "get_text", lambda url, **k: ("https://portal.example.org/ds/1", html_page))
    monkeypatch.setattr(kaggle, "_auth_header", lambda: {})

    def files(**rec):
        res._CACHE.clear()
        base = {"id": "x", "provider": "Other", "canonicalUrl": "", "sourceLinks": [], "files": []}
        return res.resolve({**base, **rec})

    r = files(canonicalUrl="https://figshare.com/articles/dataset/crashes/777")
    assert r["via"] == "Figshare API" and r["files"][0]["format"] == "parquet"
    r = files(canonicalUrl="https://data.cityofnewyork.us/Public-Safety/Motor-Vehicle-Collisions-Crashes/h9gi-nx95")
    assert r["files"][0]["url"].endswith("/api/views/h9gi-nx95/rows.csv?accessType=DOWNLOAD") and r["files"][0]["supported"]
    r = files(canonicalUrl="https://catalog.data.gov/dataset/road-incidents")
    assert r["via"] == "CKAN API" and [f["supported"] for f in r["files"]] == [True, False]
    r = files(canonicalUrl="https://dataverse.harvard.edu/dataset.xhtml?persistentId=doi:10.7910/DVN/ABC")
    assert r["files"][0]["name"] == "accidents.csv" and r["files"][0]["url"].endswith("/api/access/datafile/42?format=original")
    r = files(canonicalUrl="https://www.kaggle.com/datasets/someone/traffic")
    assert r["signInRequired"] and not r["files"] and "upload" in r["note"]
    r = files(canonicalUrl="https://portal.example.org/ds/1")
    assert {f["url"] for f in r["files"]} == {"https://cdn.example.org/a.csv", "https://portal.example.org/files/b.parquet"}


def test_blob_upload_token_and_guard(client, monkeypatch, traffic):
    monkeypatch.setenv("BLOB_READ_WRITE_TOKEN", "vercel_blob_rw_Store123_secret")
    r = client.post("/api/blob/upload-token", json={"type": "blob.generate-client-token", "payload": {"pathname": "uploads/x/data.csv"}})
    assert r.status_code == 200 and r.json()["clientToken"].startswith("vercel_blob_client_Store123_")
    assert client.post("/api/blob/upload-token", json={"type": "blob.generate-client-token", "payload": {"pathname": "../x.exe"}}).status_code == 400
    client.get("/api/live/search", params={"provider": "datacite", "q": "traffic incidents"})
    rid = next(i["id"] for i in client.get("/api/datasets", params={"q": "traffic incidents"}).json()["items"] if "Nigeria" in i["title"])
    bad = client.post(f"/api/datasets/{rid}/analyze/blob", json={"url": "https://evil.example/x.csv", "name": "x.csv"})
    assert bad.status_code == 422
    assert client.get("/api/discover/meta").json()["capabilities"]["uploadMode"] == "blob"
