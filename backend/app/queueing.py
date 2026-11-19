"""Worker presence and queue health.

The API only records jobs (analysis runs and starter-pack runs); `python -m app.worker` runs them. Each worker
writes a heartbeat row to the shared database, which lets the API say *why* a job is waiting (no worker has ever
connected, the worker went quiet, or it's busy with another job) instead of leaving people on an endless
"Queued". Nothing secret is stored or returned: the fingerprints below are short one-way hashes that only
tell the API whether the worker and the API were given the same Blob token, database and secret key.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import os
import socket

from . import blob, config, durable


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _iso(t: dt.datetime | None = None) -> str:
    return (t or _now()).isoformat(timespec="microseconds")


def _fp(value: str) -> str | None:
    return hashlib.sha256(value.encode()).hexdigest()[:8] if value else None


def blob_fp() -> str | None:
    return _fp(blob.token())


def secret_fp() -> str | None:
    return _fp(os.getenv("DSP_SECRET_KEY", ""))


def db_fp() -> str:
    """Host + database name only (never the credentials), so two processes can confirm they share a database."""
    if not durable.IS_POSTGRES:
        return "sqlite"
    from urllib.parse import urlparse

    u = urlparse(durable.DATABASE_URL)
    return _fp(f"{u.hostname}{u.path}") or "postgres"


# ------------------------------------------------------------------ worker side
def beat(name: str, kind: str = "all", current_run: str | None = None, *, started_at: str | None = None) -> None:
    now = _iso()
    row = (name, kind, started_at or now, now, current_run, "1", blob_fp(), secret_fp(), db_fp(), socket.gethostname())
    durable.execute(
        "insert into workers (name, kind, started_at, heartbeat_at, current_run, version, blob_fp, secret_fp, db_fp, host) "
        "values (?,?,?,?,?,?,?,?,?,?) on conflict (name) do update set heartbeat_at=excluded.heartbeat_at, "
        "current_run=excluded.current_run, blob_fp=excluded.blob_fp, secret_fp=excluded.secret_fp, db_fp=excluded.db_fp", row)


def forget(name: str) -> None:
    durable.execute("delete from workers where name=?", (name,))


def _age(ts: str | None) -> float | None:
    if not ts:
        return None
    try:
        t = dt.datetime.fromisoformat(ts)
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.UTC)
    return max(0.0, (_now() - t).total_seconds())


def workers() -> list[dict]:
    rows = durable.query("select name, kind, started_at, heartbeat_at, current_run, blob_fp, secret_fp, db_fp from workers "
                         "order by heartbeat_at desc")
    for r in rows:
        r["age"] = _age(r["heartbeat_at"])
        r["live"] = r["age"] is not None and r["age"] <= config.WORKER_STALE_SECONDS
    return rows


def live_worker_names() -> set[str]:
    return {w["name"] for w in workers() if w["live"]}


# ------------------------------------------------------------------ API side
def _counts() -> dict:
    out = {}
    for table, key in (("analysis_runs", "analysis"), ("pack_runs", "pack")):
        q = durable.one(f"select count(*) as n, min(created_at) as oldest from {table} where status='queued'"
                        + (" and job is not null" if table == "analysis_runs" else ""))
        r = durable.one(f"select count(*) as n from {table} where status='running'")
        out[key] = {"queued": int(q["n"]), "oldest": q["oldest"], "running": int(r["n"])}
    return out


def _phrase(seconds: float | None) -> str:
    if seconds is None:
        return "a while ago"
    if seconds < 90:
        return f"{int(seconds)} s ago"
    if seconds < 5400:
        return f"{int(seconds // 60)} min ago"
    return f"{seconds / 3600:.1f} h ago"


def status() -> dict:
    """What the Run view and /api/worker/status show. Only meaningful in queue mode."""
    if config.RUN_MODE != "queue":
        return {"mode": config.RUN_MODE, "state": "inline", "message": "Runs execute inside the app; no separate worker is needed."}
    ws = workers()
    live = [w for w in ws if w["live"]]
    c = _counts()
    queued = c["analysis"]["queued"] + c["pack"]["queued"]
    running = c["analysis"]["running"] + c["pack"]["running"]
    oldest = min([t for t in (c["analysis"]["oldest"], c["pack"]["oldest"]) if t], default=None)
    me = {"blob": blob_fp(), "secret": secret_fp(), "db": db_fp()}
    warnings = []
    for w in live:
        if w["db_fp"] and w["db_fp"] != me["db"]:
            warnings.append("database")  # can't normally happen (it read the same table), but costs nothing to check
        if me["blob"] and w["blob_fp"] != me["blob"]:
            warnings.append("blob_token")
        if me["secret"] and w["secret_fp"] != me["secret"]:
            warnings.append("secret_key")
    warnings = sorted(set(warnings))
    if live:
        busy = running >= len(live)
        state = "busy" if busy and queued else "online"
        message = (f"{len(live)} worker{'s' if len(live) != 1 else ''} online." if not busy or not queued
                   else f"All {len(live)} worker{'s are' if len(live) != 1 else ' is'} busy; {queued} job{'s' if queued != 1 else ''} waiting.")
    elif ws:
        state = "offline"
        message = (f"The worker last checked in {_phrase(ws[0]['age'])}. Restart it (python -m app.worker); "
                   "queued jobs stay in line and run as soon as it's back.")
    else:
        state = "none"
        message = ("No worker has ever connected to this app's database, so queued jobs can't start. Start one with "
                   "`python -m app.worker` (or `docker compose --profile worker up -d`) using this deployment's DATABASE_URL.")
    return {"mode": "queue", "state": state, "message": message, "live": len(live), "queued": queued, "running": running,
            "oldestQueuedSeconds": _age(oldest), "lastSeenSeconds": ws[0]["age"] if ws else None, "warnings": warnings,
            "workers": [{"name": w["name"], "live": w["live"], "lastSeenSeconds": w["age"], "currentRun": w["current_run"]} for w in ws[:5]]}


def queue_info(table: str, created_at: str, run_id: str) -> dict | None:
    """For one queued run: where it is in line and what is (not) there to run it."""
    if config.RUN_MODE != "queue":
        return None
    st = status()
    ahead = durable.one(f"select count(*) as n from {table} where status='queued' and created_at < ?"
                        + (" and job is not null" if table == "analysis_runs" else ""), (created_at,))
    n = int(ahead["n"]) if ahead else 0
    if st["state"] in ("none", "offline"):
        headline = "Waiting for a worker: none is connected" if st["state"] == "none" else "Waiting for a worker: it went offline"
    elif n or st["state"] == "busy":
        headline = f"Waiting in line: {n} job{'s' if n != 1 else ''} ahead" if n else "Waiting for a free worker"
    else:
        headline = "A worker is picking this up"
    return {"state": st["state"], "headline": headline, "detail": st["message"], "ahead": n, "waitingSeconds": _age(created_at),
            "warnings": st["warnings"]}


def reap() -> dict:
    """Requeue what a vanished worker was running; fail what nobody picked up in QUEUE_MAX_AGE_HOURS.

    Called by workers on every loop and by the API when it reads a run. Running jobs of a worker whose heartbeat is
    stale go back in line (their job payload is still stored) up to twice; after that they fail with the reason.
    """
    live = live_worker_names()
    now = _iso()
    out = {"requeued": 0, "failed": 0}
    for table in ("analysis_runs", "pack_runs"):
        rows = durable.query(f"select id, worker from {table} where status='running' and worker is not null")
        for r in rows:
            if r["worker"] in live:
                continue
            attempts = durable.one(f"select attempts from {table} where id=?", (r["id"],)) if table == "pack_runs" else None
            tries = int(attempts["attempts"]) if attempts else 0
            if table == "pack_runs" and tries < 2 or table == "analysis_runs" and _requeue_analysis(r["id"]):
                if table == "pack_runs":
                    durable.execute("update pack_runs set status='queued', worker=null, attempts=attempts+1, started_at=null, "
                                    "log = log || ? where id=? and status='running'",
                                    (f"\n[{now[11:19]}] The worker running this stopped; the run was put back in line.\n", r["id"]))
                out["requeued"] += 1
            else:
                msg = "The worker running this stopped and the job could not be retried. Run it again."
                if table == "pack_runs":
                    durable.execute("update pack_runs set status='failed', finished_at=?, error=? where id=? and status='running'",
                                    (now, msg, r["id"]))
                else:
                    durable.execute("update analysis_runs set status='failed', finished_at=?, error_kind='interrupted', error=? "
                                    "where id=? and status='running'", (now, msg, r["id"]))
                out["failed"] += 1
    durable.execute("delete from workers where heartbeat_at < ?", (_iso(_now() - dt.timedelta(days=7)),))  # long-gone workers
    cutoff = _iso(_now() - dt.timedelta(hours=config.QUEUE_MAX_AGE_HOURS))
    msg = (f"No worker picked this up within {config.QUEUE_MAX_AGE_HOURS:g} hours. Start the worker and run it again.")
    n = durable.execute_count("update analysis_runs set status='failed', finished_at=?, error_kind='interrupted', error=? "
                              "where status='queued' and created_at < ?", (now, msg, cutoff))
    n += durable.execute_count("update pack_runs set status='failed', finished_at=?, error=? where status='queued' and created_at < ?",
                               (now, msg, cutoff))
    out["failed"] += n
    return out


_last_reap = 0.0


def reap_throttled(every: float = 5.0) -> None:
    """Reads of a queued/running run call this; at most one sweep per few seconds per process."""
    global _last_reap
    import time

    if time.monotonic() - _last_reap >= every:
        _last_reap = time.monotonic()
        reap()


def _requeue_analysis(run_id: str) -> bool:
    """Analysis jobs: requeue once (marker line in the log) while the stored job payload still exists."""
    row = durable.one("select job, log from analysis_runs where id=?", (run_id,))
    if not row or not row["job"] or "was put back in line" in (row["log"] or ""):
        return False
    durable.execute("update analysis_runs set status='queued', worker=null, stage=null, progress=null, log = log || ? "
                    "where id=? and status='running'", (f"{_iso()[11:19]}  The worker running this stopped; the run was put back in line\n", run_id))
    return True
