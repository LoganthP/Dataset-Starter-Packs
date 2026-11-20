"""Run pack analyses as isolated subprocesses and track them in the durable store (db.py).

Each pack is executed exactly the way a user would run it from a terminal:
``python analysis.py --mode <mode> --out <run dir> --param k=v`` with the pack directory as cwd.
That keeps packs self-contained (no import collisions) and guarantees the web app shows the
same results as the CLI and the notebook.

Two modes (config.RUN_MODE):
  thread  the API runs the subprocess itself (local dev, Docker without a worker). Files live in RUNS_DIR.
  queue   the API only records the run; `python -m app.worker` claims it, runs the same subprocess, streams the log into
          the database and, when it finishes, stores results.json and every chart file as run artifacts. The API serves
          them from the database, so a Vercel deployment shows results after refresh with no shared disk.
"""
from __future__ import annotations

import codecs
import datetime as dt
import json
import mimetypes
import os
import re
import shutil
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
    queued = config.RUN_MODE == "queue"
    run = {"id": uuid.uuid4().hex[:12], "slug": slug, "mode": mode, "params": clean, "status": "queued", "created_at": _now(),
           "worker": None if queued else "thread"}
    db.insert(run)
    if not queued:
        run_dir(run["id"]).mkdir(parents=True, exist_ok=True)
        _executor.submit(_execute, run["id"], slug, mode, clean)
    return with_queue(db.get(run["id"]))


def with_queue(run: dict | None) -> dict | None:
    """Queued runs carry where they are in line and whether a worker is there (see queueing.queue_info)."""
    if run and run["status"] == "queued" and config.RUN_MODE == "queue":
        from . import inline, queueing

        queueing.reap_throttled()
        run["queue"] = queueing.queue_info("pack_runs", run["created_at"], run["id"], inline_ok=inline.pack_eligible(run))
    return run


def _last_error(log_text: str) -> str:
    """Pull the most useful lines out of a traceback (DataError messages carry recovery hints)."""
    lines = [ln for ln in log_text.strip().splitlines() if ln.strip()]
    for i in range(len(lines) - 1, -1, -1):
        if re.match(r"^[\w.]*(Error|Exception)\b", lines[i]):
            return "\n".join(lines[i:])[:1500]
    return "\n".join(lines[-6:])[:1500] if lines else "The run failed without output."


def _canceled_now(run_id: str, ship: bool) -> bool:
    return run_id in _canceled or (ship and db.cancel_requested(run_id))


class _Pump(threading.Thread):
    """Worker mode: stream the log file into the database and watch for a cancel request while the subprocess runs."""

    def __init__(self, run_id: str, log_path: Path):
        super().__init__(daemon=True, name=f"pack-pump-{run_id}")
        self.run_id, self.log_path, self.offset, self.stop = run_id, log_path, 0, threading.Event()
        self.dec = codecs.getincrementaldecoder("utf-8")(errors="replace")

    def flush(self) -> None:
        if not self.log_path.exists():
            return
        with open(self.log_path, "rb") as f:
            f.seek(self.offset)
            chunk = f.read(500_000)
        self.offset += len(chunk)
        db.append_log(self.run_id, self.dec.decode(chunk))

    def run(self) -> None:
        while not self.stop.wait(1.5):
            try:
                self.flush()
                if db.cancel_requested(self.run_id):
                    _canceled.add(self.run_id)
                    with _procs_lock:
                        proc = _procs.get(self.run_id)
                    if proc and proc.poll() is None:
                        proc.terminate()
            except Exception:  # noqa: BLE001 - a flaky database call must not kill the run
                pass


def _store_outputs(run_id: str, out: Path) -> list[str]:
    """Keep results.json and the chart files in the database. Returns notes about anything left out."""
    notes, total = [], 0
    for path in sorted(out.iterdir()):
        if not path.is_file() or path.name == "run.log":
            continue
        size = path.stat().st_size
        if total + size > config.MAX_ARTIFACT_BYTES:
            notes.append(f"{path.name} ({size / 1e6:.1f} MB) was not stored: over the {config.MAX_ARTIFACT_BYTES / 1e6:.0f} MB per-run limit")
            continue
        total += size
        db.put_artifact(run_id, path.name, mimetypes.guess_type(path.name)[0] or "application/octet-stream", path.read_bytes())
    return notes


def _execute(run_id: str, slug: str, mode: str, params: dict, *, ship: bool = False, timeout: float | None = None) -> None:
    if _canceled_now(run_id, ship):
        db.update(run_id, status="canceled", finished_at=_now())
        return
    out = run_dir(run_id)
    out.mkdir(parents=True, exist_ok=True)
    log_path = out / "run.log"
    pack = catalog.pack_dir(slug)
    cmd = [config.PACK_PYTHON or sys.executable, "-u", "analysis.py", "--mode", mode, "--out", str(out)]
    for k, v in params.items():
        cmd += ["--param", f"{k}={v}"]
    env = {**os.environ, "MPLBACKEND": "Agg", "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1",
           "MPLCONFIGDIR": str(config.STATE_DIR / "mpl")}  # serverless home directories are read-only
    if config.ON_VERCEL and not config.PACK_PYTHON:
        # The function's dependencies sit on the web app's import path, not in the interpreter's default one: a pack started as
        # its own process would fail with "No module named 'numpy'". Hand it the same path.
        env["PYTHONPATH"] = os.pathsep.join(p for p in [*sys.path, os.environ.get("PYTHONPATH", "")] if p)
    # Split CPU cores between parallel runs so OpenMP/BLAS threads don't oversubscribe the machine.
    threads = str(max(1, (os.cpu_count() or 2) // config.MAX_PARALLEL_RUNS))
    for var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        env.setdefault(var, threads)
    started = time.monotonic()
    if not ship:  # a worker already marked it running when it claimed it
        db.update(run_id, status="running", started_at=_now())
    pump = _Pump(run_id, log_path) if ship else None
    if pump:
        pump.start()
    try:
        with open(log_path, "w", encoding="utf-8") as log:
            log.write(f"$ python analysis.py --mode {mode}" + "".join(f" --param {k}={v}" for k, v in params.items()) + "\n")
            log.flush()
            proc = subprocess.Popen(cmd, cwd=pack, stdout=log, stderr=subprocess.STDOUT, env=env)
            with _procs_lock:
                _procs[run_id] = proc
            try:
                code = proc.wait(timeout=timeout or config.RUN_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                code = -9
                log.write(f"\nTimeoutError: run exceeded {int(timeout or config.RUN_TIMEOUT_SECONDS)} s and was stopped.\n")
    except Exception as exc:  # e.g. interpreter not found
        if pump:
            pump.stop.set()
            pump.join(5)
            pump.flush()
        db.update(run_id, status="failed", finished_at=_now(), error=f"Could not start the pack: {exc}")
        return
    finally:
        with _procs_lock:
            _procs.pop(run_id, None)
    if pump:
        pump.stop.set()
        pump.join(5)
        pump.flush()

    duration = round(time.monotonic() - started, 2)
    results_path = out / "results.json"
    if run_id in _canceled or (ship and db.cancel_requested(run_id)):
        db.update(run_id, status="canceled", finished_at=_now(), duration_s=duration, exit_code=code)
    elif code == 0 and results_path.exists():
        results = json.loads(results_path.read_text(encoding="utf-8"))
        if ship:  # store before the status flips, so "succeeded" always has its results and charts behind it
            db.save_results(run_id, results)
            for note in _store_outputs(run_id, out):
                db.append_log(run_id, f"\n{note}\n")
        db.update(run_id, status="succeeded", finished_at=_now(), duration_s=duration, exit_code=0,
                  headline=results.get("headline"))
    else:
        error = _last_error(log_path.read_text(encoding="utf-8", errors="replace"))
        db.update(run_id, status="failed", finished_at=_now(), duration_s=duration, exit_code=code, error=error)
    if ship:
        shutil.rmtree(out, ignore_errors=True)  # the database has everything; don't fill the worker's disk
    _canceled.discard(run_id)


def execute_claimed(run: dict, *, timeout: float | None = None) -> None:
    """Worker entry point for a run it has claimed (status is already 'running')."""
    _execute(run["id"], run["slug"], run["mode"], run["params"], ship=True, timeout=timeout)


def cancel(run_id: str) -> bool:
    run = db.get(run_id)
    if not run or run["status"] not in ("queued", "running"):
        return False
    if config.RUN_MODE == "queue":
        if run["status"] == "queued":  # nobody has claimed it: cancel right here
            db.update(run_id, status="canceled", finished_at=_now())
            return True
        return db.request_cancel(run_id)  # the worker watches this flag and stops the process
    _canceled.add(run_id)
    with _procs_lock:
        proc = _procs.get(run_id)
    if proc and proc.poll() is None:
        proc.terminate()
        return True
    if run["status"] == "queued":
        db.update(run_id, status="canceled", finished_at=_now())
        return True
    return False


def results(run_id: str) -> dict | None:
    path = run_dir(run_id) / "results.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return db.results(run_id)  # produced by a worker: stored in the database


def read_file(run_id: str, name: str) -> tuple[bytes | Path, str | None] | None:
    """A file a run produced: local copy first, then the one the worker stored. None when there isn't one."""
    base = run_dir(run_id).resolve()
    path = (base / name).resolve()
    if path.parent == base and path.is_file():
        return path, None
    art = db.get_artifact(run_id, name)
    return (art[0], art[1]) if art else None


def read_log(run_id: str, offset: int = 0) -> dict:
    path = run_dir(run_id) / "run.log"
    if not path.exists():
        return db.read_log(run_id, offset) or {"text": "", "offset": 0}
    with open(path, "rb") as f:
        f.seek(max(0, offset))
        chunk = f.read(200_000)
    return {"text": chunk.decode("utf-8", errors="replace"), "offset": offset + len(chunk)}
