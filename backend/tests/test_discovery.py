"""Discovery: catalog normalization, requirement checks, benchmark, adapters, imports and API."""
import os
import shutil
from pathlib import Path

import pytest

STATE = Path(__file__).parent / ".state-discovery"
shutil.rmtree(STATE, ignore_errors=True)
os.environ["DSP_STATE_DIR"] = str(STATE)

from fastapi.testclient import TestClient  # noqa: E402

from app.discovery import benchmark, importer, search, store  # noqa: E402
from app.discovery.adapters import cmr, kaggle, uci  # noqa: E402
from app.discovery.adapters.http import AdapterError  # noqa: E402
from app.discovery.fit import evaluate  # noqa: E402
from app.discovery.vocab import Criteria, parse_query  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True, scope="module")
def seeds():
    report = store.load_seeds()
    assert report["errors"] == []
    return report


# ---------------------------------------------------------------- P0: normalized catalog
def test_every_record_has_identity_and_source():
    recs = store.all_records()
    assert len(recs) >= 14
    for r in recs.values():
        for key in ("id", "publisher", "provider", "canonicalUrl", "description"):
            assert r[key], f"{r['id']} missing {key}"
        assert r["canonicalUrl"].startswith("https://")
        assert r["license"]["commercialUse"] in ("allowed", "not-allowed", "conditional", "unknown")


def test_each_pack_is_one_result_with_its_source():
    recs = store.all_records()
    packs = {r["packId"]: r for r in recs.values() if r.get("packId")}
    assert set(packs) == {"uci-bike-demand", "nasa-bengaluru-weather", "nasa-exoplanets", "uci-dry-bean", "kaggle-olist-delivery"}
    bike = packs["uci-bike-demand"]
    assert bike["id"] == "uci.275" and bike["curated"]["offlineSample"] and bike["curated"]["notebook"]
    res = search.search({"q": "bike sharing"})
    assert [i["id"] for i in res["items"]].count("uci.275") == 1


def test_unknown_values_stay_explicit():
    nyc = store.all_records()["socrata-nyc.h9gi-nx95"]
    assert nyc["coverage"]["temporal"]["status"] == "unknown"
    assert nyc["coverage"]["temporal"]["start"] is None
    assert nyc["license"]["status"] == "unknown"


# ---------------------------------------------------------------- P0: relevance + requirement checks
def test_parser_routewatch():
    c = parse_query("I need traffic incident data for RouteWatch. It should have latitude, longitude, and timestamps, "
                    "cover at least one year, and be available as CSV.")
    assert c.fields == ["latlon", "timestamp"] and c.min_years == 1 and c.formats == ["csv"] and c.region is None
    assert "traffic" in c.topic and "incident" in c.topic


def test_coordinates_as_api_input_do_not_satisfy_record_level_requirement():
    power = store.all_records()["nasa-power.daily-point"]
    ev = evaluate(power, Criteria(fields=["latlon"]))
    assert ev["fit"] == "does-not-meet"
    assert "API input" in ev["reasons"][0]["text"]


def test_routewatch_explanations_and_groups():
    res = search.search(benchmark.params_for(
        "traffic incident data with latitude, longitude and timestamps, at least one year, CSV"))
    by = {i["id"]: i for i in res["items"]}
    nyc = by["socrata-nyc.h9gi-nx95"]
    assert nyc["fit"] == "needs-verification"
    assert any(r["text"].startswith("Date coverage is unverified") for r in nyc["reasons"])
    assert any("Latitude and longitude are documented" in r["text"] for r in nyc["reasons"])
    # Broaden: downgrade the coverage requirement to a preference and NYC becomes a confirmed match.
    broad = search.search({**benchmark.params_for("traffic incident data with latitude, longitude and timestamps, at least one year, CSV"),
                           "soft": "min_years"})
    assert {i["id"]: i["fit"] for i in broad["items"]}["socrata-nyc.h9gi-nx95"] == "meets"


def test_no_confirmed_match_with_unconfirmed_requirement_any_combo():
    combos = [{"fields": "latlon,timestamp"}, {"min_years": "5"}, {"formats": "csv,parquet"}, {"commercial": "1"},
              {"region": "bengaluru", "granularity": "daily"}, {"fields": "target_label", "commercial": "1", "formats": "csv"}]
    for combo in combos:
        res = search.search({**combo, "include_failed": "1", "page_size": "50"})
        for item in res["items"]:
            if item["fit"] == "meets":
                assert all(r["outcome"] == "met" for r in item["reasons"] if r["required"]), (combo, item["id"])


def test_filters_and_or_semantics():
    both = search.search({"provider": "UCI,Kaggle", "page_size": "50"})
    assert {i["provider"] for i in both["items"]} == {"UCI", "Kaggle"}
    narrowed = search.search({"provider": "UCI,Kaggle", "access": "sign-in", "page_size": "50"})
    assert {i["provider"] for i in narrowed["items"]} == {"Kaggle"}
    provider_facet = {f["value"]: f["count"] for f in narrowed["facets"]["provider"]}
    assert provider_facet["UCI"] == 0 and provider_facet["Kaggle"] >= 2  # counts exclude the group's own filter only


def test_benchmark_has_no_violations():
    report = benchmark.run()
    assert report["violations"] == 0, report
    assert report["top5_hit_rate"] == 1.0, report


# ---------------------------------------------------------------- P1: adapters + imports
UCI_META = {"uci_id": 9001, "name": "Synthetic Traffic Probe", "abstract": "Hourly probe counts.", "area": "Other",
            "characteristics": ["Multivariate", "Time-Series"], "tasks": ["Regression"], "num_instances": 100,
            "last_updated": "Fri Mar 15 2024", "data_url": "https://archive.ics.uci.edu/static/public/9001/data.csv",
            "repository_url": "https://archive.ics.uci.edu/dataset/9001/synthetic",
            "variables": [{"name": "timestamp", "role": "Feature", "type": "Date", "units": None, "description": "Hour"},
                          {"name": "Latitude", "role": "Feature", "type": "Continuous", "units": "deg", "description": ""},
                          {"name": "count", "role": "Target", "type": "Integer", "units": None, "description": "Vehicles"}]}
CMR_ITEM = {"meta": {"concept-id": "C1234-TEST", "revision-date": "2026-11-01T00:00:00Z"},
            "umm": {"EntryTitle": "Test Daily Rain", "Abstract": "Daily rain.", "DataCenters": [{"ShortName": "TEST/DAAC"}],
                    "TemporalExtents": [{"RangeDateTimes": [{"BeginningDateTime": "2000-01-01T00:00:00Z"}], "EndsAtPresentFlag": True}],
                    "SpatialExtent": {"HorizontalSpatialDomain": {"Geometry": {"BoundingRectangles": [
                        {"WestBoundingCoordinate": -180, "EastBoundingCoordinate": 180, "NorthBoundingCoordinate": 90, "SouthBoundingCoordinate": -90}]}}},
                    "ArchiveAndDistributionInformation": {"FileDistributionInformation": [{"Format": "netCDF-4"}]},
                    "RelatedUrls": [{"Type": "DATA SET LANDING PAGE", "URL": "https://example.nasa.gov/test-rain"}],
                    "DOI": {"DOI": "10.0000/test"}}}
KAGGLE_ITEM = {"ref": "someone/city-crashes", "title": "City Crashes", "subtitle": "Crash points", "ownerName": "Someone",
               "licenseName": "CC BY-NC-SA 4.0", "totalBytes": 1234, "lastUpdated": "2026-05-01T10:00:00Z", "tags": [{"name": "traffic"}]}


def test_uci_normalize_detects_concepts():
    rec = uci.normalize(UCI_META)
    concepts = {f["name"]: f["concepts"] for f in rec["fields"]}
    assert concepts["timestamp"] == ["timestamp"] and concepts["Latitude"] == ["latlon"] and concepts["count"] == ["target_label"]
    assert rec["schemaStatus"] == "complete" and rec["license"]["status"] == "unknown"
    assert rec["sourceUpdatedAt"] == "2024-03-15" and "forecasting" in rec["purposes"]


def test_cmr_and_kaggle_normalize():
    c = cmr.normalize(CMR_ITEM)
    assert c["id"] == "nasa-cmr.c1234-test" and c["coverage"]["temporal"]["start"] == "2000-01-01"
    assert c["coverage"]["spatial"]["regions"] == ["global"] and c["formats"]["values"] == ["netcdf"]
    k = kaggle.normalize(KAGGLE_ITEM)
    assert k["id"] == "kaggle.someone-city-crashes" and k["license"]["commercialUse"] == "not-allowed"
    assert k["access"]["signInRequired"] is True and k["schemaStatus"] == "unknown"


def test_import_dedupes_and_survives_an_outage():
    seed_492 = uci.normalize({**UCI_META, "uci_id": 492, "repository_url": "https://archive.ics.uci.edu/dataset/492/metro+interstate+traffic+volume"})

    def fake_uci(term, limit):
        return [uci.normalize(UCI_META), seed_492]

    def down(term, limit):
        raise AdapterError("TimeoutError: timed out")

    before = len(store.all_records())
    importer.run(adapters={"uci": ("UCI", fake_uci), "kaggle": ("Kaggle", down)})
    after = store.all_records()
    assert len(after) == before + 1  # 9001 added; 492 merged into the reviewed seed, not duplicated
    assert after["uci.492"]["origin"] == "seed" and after["uci.492"]["lastFetchedAt"]
    assert after["uci.9001"]["reviewStatus"] == "unreviewed"
    statuses = {s["source"]: s for s in store.source_statuses()}
    assert statuses["kaggle"]["status"] == "error" and "Timeout" in statuses["kaggle"]["detail"]
    assert statuses["uci"]["status"] == "ok"
    # Kaggle is down, yet indexed Kaggle records are still searchable.
    res = search.search({"q": "traffic accidents"})
    assert "kaggle.sobhanmoosavi-us-accidents" in [i["id"] for i in res["items"]]
    # Re-running the import doesn't duplicate anything.
    importer.run(adapters={"uci": ("UCI", fake_uci)})
    assert len(store.all_records()) == before + 1


# ---------------------------------------------------------------- API
def test_api_search_detail_compare(client):
    parsed = client.get("/api/criteria/parse", params={"q": "daily weather for Bengaluru over 10 years"}).json()
    assert parsed["region"] == "bengaluru" and parsed["granularity"] == "daily" and parsed["min_years"] == 10
    res = client.get("/api/datasets", params={"q": "weather", "region": "bengaluru", "granularity": "daily", "min_years": "10"}).json()
    assert res["items"][0]["fit"] == "meets"
    assert {"provider", "purpose", "kind", "access", "license", "difficulty", "ready"} <= set(res["facets"])
    d = client.get("/api/datasets/nasa-power.daily-point", params={"fields": "latlon"}).json()
    assert d["fit"] == "does-not-meet" and d["fields"] and d["statuses"]["metadataReviewed"]["state"] == "ok"
    assert d["statuses"]["sampleRan"]["state"] in ("pending", "ok")
    cmp_ = client.get("/api/datasets/compare", params={"ids": "uci.275,uci.492,socrata-nyc.h9gi-nx95", "commercial": "1"}).json()
    assert [x["id"] for x in cmp_["items"]] == ["uci.275", "uci.492", "socrata-nyc.h9gi-nx95"]
    assert cmp_["items"][2]["fit"] == "needs-verification"
    assert client.get("/api/datasets/nope").status_code == 404
    meta = client.get("/api/discover/meta").json()
    assert meta["total"] >= 14 and meta["curated"] == 5


def test_api_curated_scope(client):
    res = client.get("/api/datasets", params={"scope": "curated", "ready": "offline-sample", "difficulty": "beginner"}).json()
    ids = {i["id"] for i in res["items"]}
    assert ids == {"uci.275", "nasa-power.daily-point", "uci.602"}
    assert all(i["curated"] for i in res["items"])
