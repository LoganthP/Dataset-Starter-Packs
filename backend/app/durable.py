"""Durable state: what must survive restarts, container recreation and serverless cold starts.

  pack_runs / run_artifacts   starter-pack runs: status, log, results and chart files (so they survive on Vercel)
  workers              heartbeat of each worker process (is anything there to run queued jobs?)
  analysis_runs        every Analyze run (report JSON, source snapshot, file URL + SHA-256)
  comparison_reports   saved comparisons (immutable snapshots)
  overlays             facts verified by an analysis (fields, dates, formats) per dataset
  curated_records      the dataset record as it was when analyzed, so a live search result stays in
                       Curated Packs even after the live-search cache is gone
  shared_live_*        live-search results (records, which query found them, provider status). Serverless instances
                       don't share /tmp: a dataset found by one instance must open, list files and analyze on another.

Backend:
  DATABASE_URL=postgres://...  -> PostgreSQL (Vercel: Neon from the Marketplace; or any Postgres)
  otherwise                     -> SQLite in DSP_STATE_DIR (local dev and Docker, on a named volume)

Everything else (search index, link checks) is a rebuildable cache and stays in local SQLite; live-search results are
mirrored to shared_live_* and pulled into the local cache on a miss.

Postgres connections are kept per thread and reused (opening one to Neon costs a TLS handshake, often 100-400 ms);
prepared statements are off so the Neon pooler (PgBouncer, transaction mode) works.
SQL here is written once with `?` placeholders and portable `insert ... on conflict` upserts.
"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager

from . import config

DATABASE_URL = config.DATABASE_URL  # DATABASE_URL, POSTGRES_URL or one prefixed Neon variable (see config)
IS_POSTGRES = DATABASE_URL.startswith(("postgres://", "postgresql://"))
SQLITE_PATH = config.STATE_DIR / "catalog.sqlite3"  # same file as the catalog cache, so existing local history is kept

TABLES = [
    """create table if not exists analysis_runs (
      id text primary key, dataset_id text not null, status text not null, created_at text not null, finished_at text,
      file_name text, file_url text, file_format text, file_bytes bigint, file_sha256 text, source text,
      log text not null default '', error text, report text)""",
    "create index if not exists analysis_by_dataset on analysis_runs(dataset_id, created_at)",
    """create table if not exists comparison_reports (
      id text primary key, name text not null, created_at text not null, dataset_ids text not null,
      analysis_run_ids text not null, criteria text not null default '', snapshot text not null)""",
    "create table if not exists overlays (record_id text primary key, json text not null, updated_at text not null)",
    "create table if not exists curated_records (id text primary key, json text not null, updated_at text not null)",
    # App accounts keep each person's provider connections and reports separate.
    """create table if not exists users (id text primary key, email text not null unique, password_hash text not null,
      created_at text not null)""",
    """create table if not exists sessions (token_hash text primary key, user_id text not null, created_at text not null,
      expires_at text not null)""",
    # Kaggle credentials, encrypted at rest (app.secrets); never returned to the browser.
    """create table if not exists provider_connections (user_id text not null, provider text not null, account text,
      secret text not null, kind text not null, created_at text not null, verified_at text, last_error text,
      primary key (user_id, provider))""",
    # Starter-pack runs (formerly a separate local SQLite file): the API queues them, a worker runs them, and the
    # log, results and chart files are stored here so the deployed app can show them after a refresh or restart.
    """create table if not exists pack_runs (
      id text primary key, slug text not null, mode text not null, params text not null default '{}', status text not null,
      created_at text not null, started_at text, finished_at text, duration_s double precision, exit_code integer,
      error text, headline text, is_sample integer, log text not null default '', worker text, attempts integer not null default 0,
      results text, cancel_requested integer not null default 0)""",
    "create index if not exists pack_runs_by_slug on pack_runs(slug, created_at)",
    """create table if not exists run_artifacts (
      run_id text not null, name text not null, content_type text not null, size bigint not null, data bytea, primary key (run_id, name))""",
    # One row per worker process; the API reads this to say whether anything is there to pick a job up.
    """create table if not exists workers (
      name text primary key, kind text not null, started_at text not null, heartbeat_at text not null, current_run text,
      version text, blob_fp text, secret_fp text, db_fp text, host text)""",
    "create table if not exists shared_live_records (id text primary key, json text not null, updated_at text not null)",
    """create table if not exists shared_live_hits (query text not null, provider text not null, record_id text not null,
      rank integer not null, fetched_at text not null, primary key (query, provider, record_id))""",
    """create table if not exists shared_live_runs (query text not null, provider text not null, status text not null, detail text,
      count integer not null default 0, ms integer not null default 0, fetched_at text not null, primary key (query, provider))""",
    """create table if not exists oauth_states (state text primary key, user_id text not null, verifier text not null,
      return_to text, created_at text not null)""",
]

# Columns added after the first release; applied with ALTER TABLE on startup (no-op when present).
MIGRATIONS = [
    ("analysis_runs", "mode", "text not null default 'full'"),
    ("analysis_runs", "stage", "text"),
    ("analysis_runs", "error_kind", "text"),
    ("analysis_runs", "progress", "text"),
    ("analysis_runs", "params", "text"),
    ("analysis_runs", "cancel_requested", "integer not null default 0"),
    ("analysis_runs", "error_detail", "text"),
    ("analysis_runs", "owner", "text"),
    ("analysis_runs", "job", "text"),
    ("analysis_runs", "worker", "text"),
    ("analysis_runs", "summary", "text"),
]

_ready = False
_init_lock = threading.Lock()
_write_lock = threading.Lock()


def backend() -> str:
    return "postgres" if IS_POSTGRES else "sqlite"


_local = threading.local()
_IDLE_PING_SECONDS = 30.0


def _pg_connect():
    import psycopg
    from psycopg.rows import dict_row

    return psycopg.connect(DATABASE_URL, autocommit=True, row_factory=dict_row, connect_timeout=10, prepare_threshold=None)


def _pg_drop() -> None:
    con = getattr(_local, "con", None)
    _local.con = None
    if con is not None:
        try:
            con.close()
        except Exception:
            pass


def _pg_con():
    """This thread's connection; reconnects when it is closed, and pings it first when it sat idle (Neon drops idle ones)."""
    import time as _t

    con = getattr(_local, "con", None)
    if con is not None and not con.closed and _t.monotonic() - getattr(_local, "used", 0.0) > _IDLE_PING_SECONDS:
        try:
            con.execute("select 1")
        except Exception:
            _pg_drop()
            con = None
    if con is None or con.closed:
        con = _local.con = _pg_connect()
    _local.used = _t.monotonic()
    return con


@contextmanager
def _raw():
    if IS_POSTGRES:
        import psycopg

        con = _pg_con()
        try:
            yield con
        except psycopg.OperationalError:
            _pg_drop()  # broken connection: the next call opens a fresh one
            raise
        return
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(SQLITE_PATH, timeout=15)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def _sql(q: str) -> str:
    return q.replace("?", "%s") if IS_POSTGRES else q


def init() -> None:
    global _ready
    with _init_lock:
        if _ready:
            return
        with _raw() as con:
            if IS_POSTGRES:  # one script on a cold start instead of ~30 round trips
                script = TABLES + [f"alter table {t} add column if not exists {c} {d}" for t, c, d in MIGRATIONS]
                # Instances that cold-start together would race "create table if not exists" (Postgres then reports a duplicate
                # pg_type row): the transaction-scoped advisory lock lets one create the schema while the others wait.
                with con.transaction():
                    con.execute("select pg_advisory_xact_lock(7243019)")
                    con.execute(";\n".join(script))
                _ready = True
                return
            for ddl in TABLES:
                con.execute(ddl.replace(" bytea", " blob").replace("double precision", "real"))
            for table, col, decl in MIGRATIONS:
                if col not in [r[1] for r in con.execute(f"pragma table_info({table})").fetchall()]:
                    con.execute(f"alter table {table} add column {col} {decl}")
        _ready = True


def query(q: str, params: tuple = ()) -> list[dict]:
    init()
    for attempt in (0, 1):  # reads are safe to repeat once on a connection the server dropped
        try:
            with _raw() as con:
                return [dict(r) for r in con.execute(_sql(q), params).fetchall()]
        except Exception as exc:
            if attempt or not IS_POSTGRES or type(exc).__name__ != "OperationalError":
                raise
    return []


def one(q: str, params: tuple = ()) -> dict | None:
    rows = query(q, params)
    return rows[0] if rows else None


def execute(q: str, params: tuple = ()) -> None:
    init()
    with _write_lock, _raw() as con:
        con.execute(_sql(q), params)


def execute_many(q: str, rows: list[tuple]) -> None:
    """One statement for many parameter rows (one round trip per batch on Postgres)."""
    if not rows:
        return
    init()
    with _write_lock, _raw() as con:
        if IS_POSTGRES:
            with con.cursor() as cur:
                cur.executemany(_sql(q), rows)
        else:
            con.executemany(q, rows)


def execute_count(q: str, params: tuple = ()) -> int:
    """Like execute(), returning the number of rows changed (used for atomic claims)."""
    init()
    with _write_lock, _raw() as con:
        cur = con.execute(_sql(q), params)
        return cur.rowcount or 0


def reset_for_tests(tables: tuple[str, ...] = ("analysis_runs", "comparison_reports", "overlays", "curated_records", "users", "sessions",
                                               "provider_connections", "oauth_states", "pack_runs", "run_artifacts", "workers", "shared_live_records",
                                               "shared_live_hits", "shared_live_runs")) -> None:
    init()
    with _raw() as con:
        for t in tables:
            con.execute(f"delete from {t}")
