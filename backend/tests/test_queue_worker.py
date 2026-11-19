"""Queue mode end to end without Vercel: API process records jobs, a worker claims and runs them, state lives in the database.

Covers what the hosted site depends on: heartbeat/status states, queued jobs surviving a stopped worker, pack runs
executing in the worker with log, results and charts stored in the database (and served after the local run directory
is gone), cancel, reaping of vanished workers, and the Blob token / upload-token endpoint.
"""
import base64
import hashlib
import hmac
import json
import os
import shutil
import time
from pathlib import Path

import pytest

os.environ.setdefault("DSP_STATE_DIR", str(Path(__file__).parent / ".state-test"))

from fastapi.testclient import TestClient  # noqa: E402

from app import blob, config, db, durable, queueing, runner, worker  # noqa: E402
from app.main import app  # noqa: E402

SLUG = "nasa-bengaluru-weather"


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(config, "RUN_MODE", "queue")
    monkeypatch.setattr(config, "PACK_RUNS_ENABLED", True)
    with TestClient(app) as c:
        durable.reset_for_tests()
        queueing._last_reap = 0.0
        yield c
        durable.reset_for_tests()


def post_run(client, mode="sample"):
    res = client.post(f"/api/packs/{SLUG}/runs", json={"mode": mode, "params": {}})
    assert res.status_code == 202, res.text
    return res.json()


def test_status_has_no_worker_then_offline_then_online(client):
    s = client.get("/api/worker/status").json()
    assert s["state"] == "none" and "python -m app.worker" in s["message"]
    queueing.beat("w1")
    assert client.get("/api/worker/status").json()["state"] == "online"
    durable.execute("update workers set heartbeat_at=?", (queueing._iso(queueing._now() - __import__("datetime").timedelta(minutes=5)),))
    s = client.get("/api/worker/status").json()
    assert s["state"] == "offline" and "Restart it" in s["message"]


def test_queued_run_says_why_it_is_waiting(client):
    run = post_run(client)
    assert run["status"] == "queued"
    q = client.get(f"/api/runs/{run['id']}").json()["queue"]
    assert q["state"] == "none" and "worker" in q["headline"].lower()
    queueing.beat("w1")
    q = client.get(f"/api/runs/{run['id']}").json()["queue"]
    assert q["state"] == "online"


def test_queued_run_is_not_expired_while_worker_is_down_and_runs_after_restart(client):
    run = post_run(client)
    assert queueing.reap()["failed"] == 0
    assert client.get(f"/api/runs/{run['id']}").json()["status"] == "queued"
    assert worker.run_once("w-restarted")  # the restarted worker picks up what was waiting
    done = client.get(f"/api/runs/{run['id']}").json()
    assert done["status"] == "succeeded", done.get("error")
    assert durable.one("select worker from pack_runs where id=?", (run["id"],))["worker"] == "w-restarted"


def test_pack_run_in_worker_stores_log_results_and_charts_in_database(client):
    run = post_run(client)
    assert worker.run_once("w1")
    rid = run["id"]
    done = client.get(f"/api/runs/{rid}").json()
    assert done["status"] == "succeeded" and done["duration_s"] is not None
    assert done["results"] and done["headline"], done
    assert client.get(f"/api/runs/{rid}/log").json()
    names = db.artifact_names(rid)
    assert any(n.endswith(".png") or n.endswith(".svg") for n in names), names
    shutil.rmtree(runner.run_dir(rid), ignore_errors=True)  # the API instance has no local copy on Vercel
    png = next(n for n in names if n.endswith((".png", ".svg")))
    res = client.get(f"/api/runs/{rid}/files/{png}")
    assert res.status_code == 200 and len(res.content) > 100 and "private" in res.headers["cache-control"]


def test_cancel_queued_and_running_flag(client):
    run = post_run(client)
    assert client.post(f"/api/runs/{run['id']}/cancel").status_code in (200, 202)
    assert client.get(f"/api/runs/{run['id']}").json()["status"] == "canceled"
    assert not worker.run_once("w1")  # nothing left to claim
    run2 = post_run(client)
    db.claim_next("w1", queueing._iso())
    assert runner.cancel(run2["id"]) and db.cancel_requested(run2["id"])


def test_reap_requeues_run_of_vanished_worker_then_fails_after_two_tries(client):
    run = post_run(client)
    db.claim_next("ghost", queueing._iso())
    assert queueing.reap() == {"requeued": 1, "failed": 0}
    assert db.get(run["id"])["status"] == "queued"
    db.claim_next("ghost", queueing._iso())
    queueing.reap()
    db.claim_next("ghost", queueing._iso())
    assert queueing.reap()["failed"] == 1
    assert "could not be retried" in db.get(run["id"])["error"]


def test_old_queued_jobs_fail_with_actionable_message(client, monkeypatch):
    run = post_run(client)
    monkeypatch.setattr(config, "QUEUE_MAX_AGE_HOURS", 0.0)
    time.sleep(0.01)
    queueing.reap()
    got = db.get(run["id"])
    assert got["status"] == "failed" and "Start the worker" in got["error"]


def test_mismatched_blob_token_is_reported_without_values(client, monkeypatch):
    monkeypatch.setenv("BLOB_READ_WRITE_TOKEN", "vercel_blob_rw_store1_aaaa")
    queueing.beat("w1")
    monkeypatch.setenv("BLOB_READ_WRITE_TOKEN", "vercel_blob_rw_store2_bbbb")
    s = client.get("/api/worker/status").json()
    assert "blob_token" in s["warnings"]
    d = client.get("/api/diagnostics").json()
    assert any("BLOB_READ_WRITE_TOKEN" in p for p in d["problems"])
    assert "aaaa" not in json.dumps(d) and "bbbb" not in json.dumps(d)


def test_doctor_runs_without_printing_secrets(client, monkeypatch, capsys):
    monkeypatch.setenv("BLOB_READ_WRITE_TOKEN", "vercel_blob_rw_store1_secretvalue")
    monkeypatch.setenv("DSP_SECRET_KEY", "super-secret-key")
    monkeypatch.setattr(blob, "check_remote", lambda: {"ok": True, "message": "reachable"})
    worker.doctor()
    out = capsys.readouterr().out
    assert "secretvalue" not in out and "super-secret-key" not in out and "database reachable" in out


# ---- Blob ----------------------------------------------------------------------------------------------------------

def _official_style_token(rw: str, payload: dict) -> str:
    store = rw.split("_")[3]
    b64 = base64.b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()
    sig = hmac.new(rw.encode(), b64.encode(), hashlib.sha256).hexdigest()
    return f"vercel_blob_client_{store}_{base64.b64encode(f'{sig}.{b64}'.encode()).decode()}"


def test_upload_token_endpoint_states(client, monkeypatch):
    monkeypatch.delenv("BLOB_READ_WRITE_TOKEN", raising=False)
    res = client.post("/api/blob/upload-token", json={"type": "blob.generate-client-token", "payload": {"pathname": "uploads/a.csv", "clientPayload": None, "multipart": False}})
    assert res.status_code == 503 and "BLOB_READ_WRITE_TOKEN" in res.text
    monkeypatch.setenv("BLOB_READ_WRITE_TOKEN", "garbage")
    assert client.post("/api/blob/upload-token", json={"type": "blob.generate-client-token", "payload": {"pathname": "uploads/a.csv"}}).status_code == 500
    monkeypatch.setenv("BLOB_READ_WRITE_TOKEN", "vercel_blob_rw_abc123_secretsecretsecret")
    res = client.post("/api/blob/upload-token", content=b"{nope", headers={"content-type": "application/json"})
    assert res.status_code == 400
    ok = client.post("/api/blob/upload-token", json={"type": "blob.generate-client-token", "payload": {"pathname": "uploads/a.csv", "clientPayload": None, "multipart": False}})
    assert ok.status_code == 200 and ok.headers["cache-control"] == "no-store"
    token = ok.json()["clientToken"]
    assert token.startswith("vercel_blob_client_abc123_") and "secretsecretsecret" not in ok.text


def test_blob_probe_classifies_failures(monkeypatch):
    import urllib.error

    def boom(code):
        def opener(req, timeout=0):
            raise urllib.error.HTTPError(req.full_url, code, "x", {}, None)
        return opener

    monkeypatch.setenv("BLOB_READ_WRITE_TOKEN", "vercel_blob_rw_abc123_x")
    for code, kind in ((403, "auth"), (404, "not_found")):
        monkeypatch.setattr(blob.urllib.request, "urlopen", boom(code))
        with pytest.raises(blob.BlobProblem) as e:
            blob.probe("https://abc123.private.blob.vercel-storage.com/uploads/a.csv")
        assert e.value.kind == kind
