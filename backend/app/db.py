"""Starter-pack run history, on the shared durable store (SQLite locally, Postgres on Vercel).

This used to be a separate local SQLite file, which a serverless function can't keep. The table now lives next to
analysis runs in `durable` so the API (Vercel) and the worker (Docker) see the same runs, logs, results and charts.
History from the old `dsp.sqlite3` file is copied in once, the first time the new table is empty.
"""
from __future__ import annotations

import json
import sqlite3

from . import config, durable

SUMMARY_COLS = ("id, slug, mode, params, status, created_at, started_at, finished_at, duration_s, exit_code, error, headline, is_sample")


def _row(r: dict | None) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    d["params"] = json.loads(d.get("params") or "{}")
    d["is_sample"] = None if d.get("is_sample") is None else bool(d["is_sample"])
    return d


def _import_legacy() -> None:
    """One-time copy of the pre-queue local history (only when the new table is empty)."""
    if not config.DB_PATH.exists() or durable.one("select 1 as x from pack_runs limit 1"):
        return
    try:
        con = sqlite3.connect(config.DB_PATH, timeout=10)
        con.row_factory = sqlite3.Row
        rows = con.execute("select * from runs").fetchall()
        con.close()
    except sqlite3.Error:
        return
    for r in rows:
        r = dict(r)
        durable.execute(
            "insert into pack_runs (id, slug, mode, params, status, created_at, started_at, finished_at, duration_s, exit_code, error, "
            "headline, is_sample, worker) values (?,?,?,?,?,?,?,?,?,?,?,?,?,?) on conflict (id) do nothing",
            (r["id"], r["slug"], r["mode"], r["params"], r["status"] if r["status"] not in ("queued", "running") else "failed",
             r["created_at"], r["started_at"], r["finished_at"], r["duration_s"], r["exit_code"], r["error"], r["headline"], r["is_sample"], "legacy"))


def init() -> None:
    durable.init()
    _import_legacy()
    if config.RUN_MODE != "queue":
        # Runs this process was executing can never finish after a restart. (Queued jobs belong to the worker: left alone.)
        durable.execute("update pack_runs set status='failed', error='Interrupted: the server restarted during this run.' "
                        "where status in ('queued','running') and worker='thread'")


def insert(run: dict) -> None:
    durable.execute("insert into pack_runs (id, slug, mode, params, status, created_at, is_sample, worker) values (?,?,?,?,?,?,?,?)",
                    (run["id"], run["slug"], run["mode"], json.dumps(run["params"]), run["status"], run["created_at"],
                     int(run["mode"] == "sample"), run.get("worker")))


def update(run_id: str, **fields) -> None:
    if not fields:
        return
    cols = ", ".join(f"{k}=?" for k in fields)
    durable.execute(f"update pack_runs set {cols} where id=?", (*fields.values(), run_id))


def get(run_id: str) -> dict | None:
    return _row(durable.one(f"select {SUMMARY_COLS} from pack_runs where id=?", (run_id,)))


def list_runs(slug: str | None = None, limit: int = 100) -> list[dict]:
    if slug:
        rows = durable.query(f"select {SUMMARY_COLS} from pack_runs where slug=? order by created_at desc limit ?", (slug, limit))
    else:
        rows = durable.query(f"select {SUMMARY_COLS} from pack_runs order by created_at desc limit ?", (limit,))
    return [_row(r) for r in rows]


def delete(run_id: str) -> None:
    durable.execute("delete from run_artifacts where run_id=?", (run_id,))
    durable.execute("delete from pack_runs where id=?", (run_id,))


# -- worker side: claim, log, results, artifacts ---------------------------------------------------------------
def claim_next(worker: str, now: str) -> dict | None:
    for row in durable.query("select id from pack_runs where status='queued' and cancel_requested=0 order by created_at limit 5"):
        if durable.execute_count("update pack_runs set status='running', worker=?, started_at=? where id=? and status='queued'",
                                 (worker, now, row["id"])):
            return get(row["id"])
    return None


def append_log(run_id: str, text: str) -> None:
    if text:
        durable.execute("update pack_runs set log = log || ? where id=?", (text, run_id))


def read_log(run_id: str, offset: int = 0) -> dict | None:
    row = durable.one("select log from pack_runs where id=?", (run_id,))
    if not row:
        return None
    data = (row["log"] or "").encode("utf-8")
    chunk = data[max(0, offset):max(0, offset) + 200_000]
    return {"text": chunk.decode("utf-8", errors="replace"), "offset": offset + len(chunk)}


def cancel_requested(run_id: str) -> bool:
    row = durable.one("select cancel_requested as c from pack_runs where id=?", (run_id,))
    return bool(row and row["c"])


def request_cancel(run_id: str) -> bool:
    """Queued runs are canceled outright; running ones are flagged for the worker, which stops the process."""
    return bool(durable.execute_count("update pack_runs set cancel_requested=1 where id=? and status in ('queued','running')", (run_id,)))


def save_results(run_id: str, results: dict) -> None:
    durable.execute("update pack_runs set results=? where id=?", (json.dumps(results), run_id))


def results(run_id: str) -> dict | None:
    row = durable.one("select results from pack_runs where id=?", (run_id,))
    return json.loads(row["results"]) if row and row["results"] else None


def put_artifact(run_id: str, name: str, content_type: str, data: bytes) -> None:
    durable.execute("insert into run_artifacts (run_id, name, content_type, size, data) values (?,?,?,?,?) "
                    "on conflict (run_id, name) do update set content_type=excluded.content_type, size=excluded.size, data=excluded.data",
                    (run_id, name, content_type, len(data), data))


def get_artifact(run_id: str, name: str) -> tuple[bytes, str] | None:
    row = durable.one("select data, content_type from run_artifacts where run_id=? and name=?", (run_id, name))
    return (bytes(row["data"]), row["content_type"]) if row and row["data"] is not None else None


def artifact_names(run_id: str) -> list[str]:
    return [r["name"] for r in durable.query("select name from run_artifacts where run_id=? order by name", (run_id,))]


def stats() -> dict:
    total = durable.one("select count(*) as n from pack_runs")["n"]
    ok = durable.one("select count(*) as n from pack_runs where status='succeeded'")["n"]
    real = durable.one("select count(*) as n from pack_runs where status='succeeded' and mode='real'")["n"]
    latest = {r["slug"]: dict(r) for r in durable.query(
        "select slug, status, mode, headline, finished_at from pack_runs r1 where created_at = "
        "(select max(created_at) from pack_runs r2 where r2.slug = r1.slug)")}
    return {"total_runs": int(total), "succeeded_runs": int(ok), "real_runs": int(real), "latest_by_pack": latest}
