"""Paths and settings. Override with environment variables (see backend/.env.example)."""
from __future__ import annotations

import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(os.getenv("DSP_REPO_ROOT", BACKEND_DIR.parent)).resolve()
PACKS_DIR = REPO_ROOT / "packs"
ON_VERCEL = bool(os.getenv("VERCEL"))
# Vercel functions can only write to /tmp; durable data goes to DATABASE_URL (see durable.py) and Blob.
STATE_DIR = Path(os.getenv("DSP_STATE_DIR") or ("/tmp/dsp-state" if ON_VERCEL else BACKEND_DIR / ".state")).resolve()
# queue: the API records jobs and a worker (python -m app.worker) runs them; thread: the API runs them itself.
# Vercel can't run minutes-long jobs, so it always queues.
RUN_MODE = os.getenv("DSP_RUN_MODE", "queue" if ON_VERCEL else "thread")


def _database_env() -> tuple[str, str]:
    """(variable name, URL). DATABASE_URL first, then POSTGRES_URL, then a single prefixed Neon/Postgres variable such as
    STORAGE_DATABASE_URL (the Vercel Marketplace adds a prefix when one is chosen while connecting the store)."""
    for name in ("DATABASE_URL", "POSTGRES_URL"):
        if os.getenv(name):
            return name, os.environ[name]
    found = sorted(k for k, v in os.environ.items() if k.endswith(("_DATABASE_URL", "_POSTGRES_URL")) and "UNPOOLED" not in k
                   and v.startswith(("postgres://", "postgresql://")))
    prefixes = {k.rsplit("_", 2)[0] for k in found}
    return (found[0], os.environ[found[0]]) if len(prefixes) == 1 else ("", "")


DATABASE_ENV, DATABASE_URL = _database_env()
HAS_SHARED_DB = bool(DATABASE_URL)
# Starter-pack runs are minutes-long subprocesses with heavy ML dependencies. Locally and in Docker the API runs them;
# on Vercel they're queued for the worker, which needs the shared Postgres to hand status, logs and charts back.
PACK_RUNS_ENABLED = os.getenv("DSP_PACK_RUNS", "1" if (not ON_VERCEL or HAS_SHARED_DB) else "0") == "1"
# A job nobody picked up for this long is failed with a clear message (hours).
QUEUE_MAX_AGE_HOURS = float(os.getenv("DSP_QUEUE_MAX_AGE_HOURS", "24"))
# A worker whose heartbeat is older than this is considered gone (seconds); it beats every HEARTBEAT_SECONDS.
WORKER_HEARTBEAT_SECONDS = float(os.getenv("DSP_WORKER_HEARTBEAT_SECONDS", "5"))
WORKER_STALE_SECONDS = float(os.getenv("DSP_WORKER_STALE_SECONDS", "30"))
# Chart and output files kept per starter-pack run (stored in Postgres).
MAX_ARTIFACT_BYTES = int(float(os.getenv("DSP_MAX_ARTIFACT_MB", "25")) * 1024 * 1024)
RUNS_DIR = STATE_DIR / "runs"
DB_PATH = STATE_DIR / "dsp.sqlite3"
FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"

# Python used to run packs. Defaults to the interpreter running the API.
PACK_PYTHON = os.getenv("DSP_PACK_PYTHON") or None
MAX_PARALLEL_RUNS = int(os.getenv("DSP_MAX_PARALLEL_RUNS", "2"))
RUN_TIMEOUT_SECONDS = int(os.getenv("DSP_RUN_TIMEOUT_SECONDS", "900"))
# Starter-pack data uploads share the app-wide transfer limit (DSP_MAX_TRANSFER_BYTES, default 2 GB).
MAX_UPLOAD_BYTES = int(float(os.getenv("DSP_MAX_UPLOAD_MB")) * 1024 * 1024) if os.getenv("DSP_MAX_UPLOAD_MB") else None
GITHUB_REPO = os.getenv("DSP_GITHUB_REPO", "")  # e.g. "LoganthP/dataset-starter-packs" for "Open on GitHub" links
CORS_ORIGINS = [o.strip() for o in os.getenv("DSP_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if o.strip()]

for d in (STATE_DIR, RUNS_DIR):
    d.mkdir(parents=True, exist_ok=True)


def max_upload_bytes() -> int:
    from .discovery import limits

    return MAX_UPLOAD_BYTES or limits.MAX_TRANSFER_BYTES
