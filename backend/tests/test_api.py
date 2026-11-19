"""API tests: run every pack in sample mode through the real subprocess runner."""
import io
import json
import os
import time
import zipfile
from pathlib import Path

import pytest

STATE = Path(__file__).parent / ".state-test"
os.environ["DSP_STATE_DIR"] = str(STATE)

from fastapi.testclient import TestClient  # noqa: E402

from app import config  # noqa: E402
from app.main import app  # noqa: E402

SLUGS = sorted(p.parent.name for p in config.PACKS_DIR.glob("*/pack.json"))


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def wait(client, run_id, timeout=180):
    deadline = time.time() + timeout
    while time.time() < deadline:
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] in ("succeeded", "failed", "canceled"):
            return run
        time.sleep(0.4)
    raise AssertionError("run did not finish")


def test_catalog_lists_five_packs(client):
    packs = client.get("/api/packs").json()
    assert {p["slug"] for p in packs} == set(SLUGS)
    assert len(SLUGS) == 5
    assert all("error" not in p for p in packs)


def test_pack_detail_has_documents(client):
    pack = client.get("/api/packs/uci-bike-demand").json()
    assert "casual" in pack["documents"]["data_dictionary"]
    assert pack["data_status"]["expected_files"] == ["hour.csv"]


def test_unknown_pack_404(client):
    assert client.get("/api/packs/nope").status_code == 404
    assert client.get("/api/packs/..%2Fetc").status_code == 404


@pytest.mark.parametrize("slug", SLUGS)
def test_every_pack_runs_in_sample_mode(client, slug):
    res = client.post(f"/api/packs/{slug}/runs", json={"mode": "sample", "params": {}})
    assert res.status_code == 202, res.text
    run = wait(client, res.json()["id"])
    assert run["status"] == "succeeded", run.get("error")
    results = run["results"]
    assert results["is_sample"] is True
    assert all(c["passed"] for c in results["checks"])
    for chart in results["charts"]:
        img = client.get(f"/api/runs/{run['id']}/files/{chart['file']}")
        assert img.status_code == 200 and img.headers["content-type"] == "image/png"
    log = client.get(f"/api/runs/{run['id']}/log").json()
    assert "Done:" in log["text"]


def test_params_are_validated(client):
    bad = client.post("/api/packs/uci-dry-bean/runs", json={"mode": "sample", "params": {"model": "svm"}})
    assert bad.status_code == 422
    unknown = client.post("/api/packs/uci-dry-bean/runs", json={"mode": "sample", "params": {"rm -rf": "1"}})
    assert unknown.status_code == 422
    rng = client.post("/api/packs/uci-bike-demand/runs", json={"mode": "sample", "params": {"holdout_fraction": 0.9}})
    assert rng.status_code == 422


def test_params_reach_the_pack(client):
    res = client.post("/api/packs/uci-dry-bean/runs", json={"mode": "sample", "params": {"model": "random_forest"}})
    run = wait(client, res.json()["id"])
    assert run["params"] == {"model": "random_forest"}
    assert run["results"]["headline"].startswith("random_forest")


def test_failed_run_reports_recovery_hint(client):
    res = client.post("/api/packs/nasa-bengaluru-weather/runs", json={"mode": "sample", "params": {"city": "delhi"}})
    run = wait(client, res.json()["id"])
    assert run["status"] == "failed"
    assert "real mode" in run["error"]


def test_file_route_blocks_traversal(client):
    runs = client.get("/api/runs").json()
    rid = runs[0]["id"]
    assert client.get(f"/api/runs/{rid}/files/..%2F..%2Fdsp.sqlite3").status_code == 404


def test_starter_zip_is_self_contained(client):
    res = client.get("/api/packs/kaggle-olist-delivery/starter.zip")
    names = zipfile.ZipFile(io.BytesIO(res.content)).namelist()
    assert "kaggle-olist-delivery/load_data.py" in names
    assert "kaggle-olist-delivery/starter.ipynb" in names
    assert not any("/data/" in n or "/outputs/" in n for n in names)


def test_upload_rejected_for_auto_download_pack(client):
    res = client.post("/api/packs/uci-bike-demand/upload", files={"file": ("x.zip", b"PK", "application/zip")})
    assert res.status_code == 400


def test_kaggle_upload_imports_files(client):
    pack = config.PACKS_DIR / "kaggle-olist-delivery"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name in ("olist_orders_dataset.csv", "olist_order_items_dataset.csv", "olist_order_reviews_dataset.csv"):
            z.write(pack / "fixtures" / f"sample_{name}", f"archive/{name}")
    try:
        res = client.post("/api/packs/kaggle-olist-delivery/upload", files={"file": ("archive.zip", buf.getvalue(), "application/zip")})
        assert res.status_code == 200, res.text
        assert res.json()["ok"] is True
        run = wait(client, client.post("/api/packs/kaggle-olist-delivery/runs", json={"mode": "real"}).json()["id"])
        assert run["status"] == "succeeded", run.get("error")
        assert run["results"]["is_sample"] is False
    finally:
        client.delete("/api/packs/kaggle-olist-delivery/data")
    assert client.get("/api/packs/kaggle-olist-delivery/data").json()["has_real_data"] is False


def test_stats(client):
    s = client.get("/api/stats").json()
    assert s["packs"] == 5 and s["succeeded_runs"] >= 5
    assert json.dumps(s)
