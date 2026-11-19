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
# Starter-pack runs are minutes-long subprocesses with heavy ML dependencies: local and Docker only.
PACK_RUNS_ENABLED = os.getenv("DSP_PACK_RUNS", "0" if ON_VERCEL else "1") == "1"
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
