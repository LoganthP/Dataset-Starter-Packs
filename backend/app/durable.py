"""Durable state: what must survive restarts, container recreation and serverless cold starts.

  analysis_runs        every Analyze run (report JSON, source snapshot, file URL + SHA-256)
  comparison_reports   saved comparisons (immutable snapshots)
  overlays             facts verified by an analysis (fields, dates, formats) per dataset
  curated_records      the dataset record as it was when analyzed, so a live search result stays in
                       Curated Packs even after the live-search cache is gone

Backend:
  DATABASE_URL=postgres://...  -> PostgreSQL (Vercel: Neon from the Marketplace; or any Postgres)
  otherwise                     -> SQLite in DSP_STATE_DIR (local dev and Docker, on a named volume)

Everything else (search index, live-search cache, link checks) is a rebuildable cache and stays in local SQLite.
SQL here is written once with `?` placeholders and portable `insert ... on conflict` upserts.
"""
from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager

from . import config

DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL") or ""
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


@contextmanager
def _raw():
    if IS_POSTGRES:
        import psycopg
        from psycopg.rows import dict_row

        con = psycopg.connect(DATABASE_URL, autocommit=True, row_factory=dict_row, connect_timeout=10)
    else:
        config.STATE_DIR.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(SQLITE_PATH, timeout=15)
        con.row_factory = sqlite3.Row
    try:
        yield con
        if not IS_POSTGRES:
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
            for ddl in TABLES:
                con.execute(ddl)
            for table, col, decl in MIGRATIONS:
                if IS_POSTGRES:
                    con.execute(f"alter table {table} add column if not exists {col} {decl}")
                elif col not in [r[1] for r in con.execute(f"pragma table_info({table})").fetchall()]:
                    con.execute(f"alter table {table} add column {col} {decl}")
        _ready = True


def query(q: str, params: tuple = ()) -> list[dict]:
    init()
    with _raw() as con:
        return [dict(r) for r in con.execute(_sql(q), params).fetchall()]


def one(q: str, params: tuple = ()) -> dict | None:
    rows = query(q, params)
    return rows[0] if rows else None


def execute(q: str, params: tuple = ()) -> None:
    init()
    with _write_lock, _raw() as con:
        con.execute(_sql(q), params)


def execute_count(q: str, params: tuple = ()) -> int:
    """Like execute(), returning the number of rows changed (used for atomic claims)."""
    init()
    with _write_lock, _raw() as con:
        cur = con.execute(_sql(q), params)
        return cur.rowcount or 0


def reset_for_tests(tables: tuple[str, ...] = ("analysis_runs", "comparison_reports", "overlays", "curated_records", "users", "sessions",
                                               "provider_connections", "oauth_states")) -> None:
    init()
    with _raw() as con:
        for t in tables:
            con.execute(f"delete from {t}")
