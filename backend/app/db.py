"""Tiny SQLite store for run history (stdlib only)."""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager

from . import config

_lock = threading.Lock()

SCHEMA = """
create table if not exists runs (
  id text primary key,
  slug text not null,
  mode text not null,
  params text not null default '{}',
  status text not null,            -- queued | running | succeeded | failed | canceled
  created_at text not null,
  started_at text,
  finished_at text,
  duration_s real,
  exit_code integer,
  error text,
  headline text,
  is_sample integer
);
create index if not exists runs_slug on runs(slug, created_at desc);
"""


@contextmanager
def connect():
    con = sqlite3.connect(config.DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init() -> None:
    with _lock, connect() as con:
        con.executescript(SCHEMA)
        # Runs interrupted by a server restart can never finish.
        con.execute("update runs set status='failed', error='Interrupted: the server restarted during this run.' "
                    "where status in ('queued','running')")


def _row(r: sqlite3.Row | None) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    d["params"] = json.loads(d.get("params") or "{}")
    d["is_sample"] = None if d.get("is_sample") is None else bool(d["is_sample"])
    return d


def insert(run: dict) -> None:
    with _lock, connect() as con:
        con.execute("insert into runs (id, slug, mode, params, status, created_at, is_sample) values (?,?,?,?,?,?,?)",
                    (run["id"], run["slug"], run["mode"], json.dumps(run["params"]), run["status"], run["created_at"],
                     int(run["mode"] == "sample")))


def update(run_id: str, **fields) -> None:
    if not fields:
        return
    cols = ", ".join(f"{k}=?" for k in fields)
    with _lock, connect() as con:
        con.execute(f"update runs set {cols} where id=?", (*fields.values(), run_id))


def get(run_id: str) -> dict | None:
    with connect() as con:
        return _row(con.execute("select * from runs where id=?", (run_id,)).fetchone())


def list_runs(slug: str | None = None, limit: int = 100) -> list[dict]:
    with connect() as con:
        if slug:
            rows = con.execute("select * from runs where slug=? order by created_at desc limit ?", (slug, limit)).fetchall()
        else:
            rows = con.execute("select * from runs order by created_at desc limit ?", (limit,)).fetchall()
    return [_row(r) for r in rows]


def delete(run_id: str) -> None:
    with _lock, connect() as con:
        con.execute("delete from runs where id=?", (run_id,))


def stats() -> dict:
    with connect() as con:
        total = con.execute("select count(*) from runs").fetchone()[0]
        ok = con.execute("select count(*) from runs where status='succeeded'").fetchone()[0]
        real = con.execute("select count(*) from runs where status='succeeded' and mode='real'").fetchone()[0]
        latest = {r["slug"]: dict(r) for r in con.execute(
            "select slug, status, mode, headline, finished_at from runs r1 where created_at = "
            "(select max(created_at) from runs r2 where r2.slug = r1.slug)").fetchall()}
    return {"total_runs": total, "succeeded_runs": ok, "real_runs": real, "latest_by_pack": latest}
