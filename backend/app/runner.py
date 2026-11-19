"""Run pack analyses as isolated subprocesses and track them in SQLite.

Each pack is executed exactly the way a user would run it from a terminal:
``python analysis.py --mode <mode> --out <run dir> --param k=v`` with the pack directory as cwd.
That keeps packs self-contained (no import collisions) and guarantees the web app shows the
same results as the CLI and the notebook.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import catalog, config, db

_executor = ThreadPoolExecutor(max_workers=config.MAX_PARALLEL_RUNS, thread_name_prefix="pack-run")
_procs: dict[str, subprocess.Popen] = {}
_procs_lock = threading.Lock()
_canceled: set[str] = set()


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def run_dir(run_id: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{12}", run_id):
        raise FileNotFoundError(run_id)
    return config.RUNS_DIR / run_id


def submit(slug: str, mode: str, params: dict) -> dict:
    meta = catalog.load_pack(slug)
    clean = catalog.validate_params(meta, mode, params)
    run = {"id": uuid.uuid4().hex[:12], "slug": slug, "mode": mode, "params": clean, "status": "queued", "created_at": _now()}
    run_dir(run["id"]).mkdir(parents=True, exist_ok=True)
    db.insert(run)
    _executor.submit(_execute, run["id"], slug, mode, clean)
    return db.get(run["id"])


def _last_error(log_text: str) -> str:
    """Pull the most useful lines out of a traceback (DataError messages carry recovery hints)."""
    lines = [ln for ln in log_text.strip().splitlines() if ln.strip()]
    for i in range(len(lines) - 1, -1, -1):
        if re.match(r"^[\w.]*(Error|Exception)\b", lines[i]):
            return "\n".join(lines[i:])[:1500]
    return "\n".join(lines[-6:])[:1500] if lines else "The run failed without output."


def _execute(run_id: str, slug: str, mode: str, params: dict) -> None:
    if run_id in _canceled:
        db.update(run_id, status="canceled", finished_at=_now())
        return
    out = run_dir(run_id)
    log_path = out / "run.log"
    pack = catalog.pack_dir(slug)
    cmd = [config.PACK_PYTHON or sys.executable, "-u", "analysis.py", "--mode", mode, "--out", str(out)]
    for k, v in params.items():
        cmd += ["--param", f"{k}={v}"]
    env = {**os.environ, "MPLBACKEND": "Agg", "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    # Split CPU cores between parallel runs so OpenMP/BLAS threads don't oversubscribe the machine.
    threads = str(max(1, (os.cpu_count() or 2) // config.MAX_PARALLEL_RUNS))
    for var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        env.setdefault(var, threads)
    started = time.monotonic()
    db.update(run_id, status="running", started_at=_now())
    try:
        with open(log_path, "w", encoding="utf-8") as log:
            log.write(f"$ python analysis.py --mode {mode}" + "".join(f" --param {k}={v}" for k, v in params.items()) + "\n")
            log.flush()
            proc = subprocess.Popen(cmd, cwd=pack, stdout=log, stderr=subprocess.STDOUT, env=env)
            with _procs_lock:
                _procs[run_id] = proc
            try:
                code = proc.wait(timeout=config.RUN_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                code = -9
                log.write(f"\nTimeoutError: run exceeded {config.RUN_TIMEOUT_SECONDS} s and was stopped.\n")
    except Exception as exc:  # e.g. interpreter not found
        db.update(run_id, status="failed", finished_at=_now(), error=f"Could not start the pack: {exc}")
        return
    finally:
        with _procs_lock:
            _procs.pop(run_id, None)

    duration = round(time.monotonic() - started, 2)
    results_path = out / "results.json"
    if run_id in _canceled:
        db.update(run_id, status="canceled", finished_at=_now(), duration_s=duration, exit_code=code)
    elif code == 0 and results_path.exists():
        results = json.loads(results_path.read_text(encoding="utf-8"))
        db.update(run_id, status="succeeded", finished_at=_now(), duration_s=duration, exit_code=0,
                  headline=results.get("headline"))
    else:
        error = _last_error(log_path.read_text(encoding="utf-8", errors="replace"))
        db.update(run_id, status="failed", finished_at=_now(), duration_s=duration, exit_code=code, error=error)


def cancel(run_id: str) -> bool:
    _canceled.add(run_id)
    with _procs_lock:
        proc = _procs.get(run_id)
    if proc and proc.poll() is None:
        proc.terminate()
        return True
    run = db.get(run_id)
    if run and run["status"] == "queued":
        db.update(run_id, status="canceled", finished_at=_now())
        return True
    return False


def results(run_id: str) -> dict | None:
    path = run_dir(run_id) / "results.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def read_log(run_id: str, offset: int = 0) -> dict:
    path = run_dir(run_id) / "run.log"
    if not path.exists():
        return {"text": "", "offset": 0}
    with open(path, "rb") as f:
        f.seek(max(0, offset))
        chunk = f.read(200_000)
    return {"text": chunk.decode("utf-8", errors="replace"), "offset": offset + len(chunk)}
