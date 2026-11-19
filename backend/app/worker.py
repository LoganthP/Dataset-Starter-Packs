"""Worker for queue mode (DSP_RUN_MODE=queue, which is always the case on Vercel).

The API only records jobs. This process claims them one at a time with an atomic UPDATE and runs them:

  * dataset analyses (analysis_runs)    -> the same pipeline as everywhere else; reports are saved to the database
  * starter-pack runs (pack_runs)       -> the pack's analysis.py as a subprocess; the log streams into the database
                                          and results.json plus every chart are stored as run artifacts

A heartbeat row (table `workers`) tells the API this worker is alive, so the Run view can say "waiting for a worker"
instead of sitting on "Queued". Run it where there is disk and time for 2 GB transfers and long analyses:

    python -m app.worker                      # from backend/; needs DATABASE_URL, DSP_SECRET_KEY (+ BLOB_READ_WRITE_TOKEN for uploads)
    python -m app.worker --doctor             # check configuration and connectivity, then exit (prints no secrets)
    docker compose --profile worker up -d     # the compose service

Uploads in queue mode go to private object storage (Vercel Blob), never to the API's local disk.
"""
from __future__ import annotations

import os

os.environ.setdefault("DSP_RUN_MODE", "queue")  # this process is the queue's consumer, whatever else is set

import logging  # noqa: E402
import signal  # noqa: E402
import socket  # noqa: E402
import sys  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402

from . import blob, config, db, durable, queueing, runner  # noqa: E402
from .discovery import analysis  # noqa: E402

log = logging.getLogger("dsp.worker")
_stop = False


def _handle(signum, frame) -> None:  # noqa: ARG001
    global _stop
    _stop = True


class Heartbeat(threading.Thread):
    """Beats while a long job runs, too (analyses and packs can take many minutes)."""

    def __init__(self, name: str):
        super().__init__(daemon=True, name="heartbeat")
        self.worker, self.current, self.started = name, None, queueing._iso()
        self.halt = threading.Event()

    def run(self) -> None:
        while not self.halt.is_set():
            try:
                queueing.beat(self.worker, "all", self.current, started_at=self.started)
            except Exception as exc:  # noqa: BLE001 - say so once per failure, keep trying
                log.warning("heartbeat failed: %s", exc.__class__.__name__)
            self.halt.wait(config.WORKER_HEARTBEAT_SECONDS)


def _oldest(table: str, extra: str = "") -> str | None:
    row = durable.one(f"select min(created_at) as t from {table} where status='queued'{extra}")
    return row["t"] if row else None


def run_once(name: str, hb: Heartbeat | None = None) -> bool:
    """Claim and run the oldest queued job (pack or analysis). Returns False when the queue is empty."""
    queueing.reap_throttled()
    a, p = _oldest("analysis_runs", " and job is not null"), _oldest("pack_runs", " and cancel_requested=0")
    order = ["pack", "analysis"] if p and (not a or p <= a) else ["analysis", "pack"]
    for kind in order:
        if kind == "pack":
            run = db.claim_next(name, queueing._iso())
            if run:
                if hb:
                    hb.current = run["id"]
                log.info("running pack %s (%s, %s)", run["id"], run["slug"], run["mode"])
                runner.execute_claimed(run)
                return True
        else:
            run = analysis.claim_next(name)
            if run:
                job = run.get("job") or {}
                if hb:
                    hb.current = run["id"]
                log.info("running analysis %s (%s)", run["id"], run["dataset_id"])
                analysis._execute(run["id"], job["rec"], job.get("fetch"), None, job.get("mode") or run.get("mode") or "sample")
                durable.execute("update analysis_runs set job=null where id=?", (run["id"],))  # not needed once it ran
                return True
    return False


def startup_report(name: str) -> list[str]:
    """Plain facts about this process's configuration (never values), and what is likely wrong."""
    notes = [f"worker {name}", f"database: {durable.backend()} ({queueing.db_fp()})", f"run mode: {config.RUN_MODE}",
             f"blob: {'configured' if blob.enabled() else 'NOT configured'}{' (' + blob.status()['storeId'] + ')' if blob.status()['storeId'] else ''}",
             f"secret key: {'set' if os.getenv('DSP_SECRET_KEY') else 'NOT set'}"]
    if not durable.IS_POSTGRES:
        notes.append("WARNING: using SQLite. A Vercel deployment's jobs live in Postgres, so this worker would never see them. "
                     "Set DATABASE_URL to the same database the app uses.")
    if not blob.enabled():
        notes.append("WARNING: no BLOB_READ_WRITE_TOKEN, so uploaded files can't be read.")
    if not os.getenv("DSP_SECRET_KEY"):
        notes.append("WARNING: no DSP_SECRET_KEY, so connected Kaggle accounts can't be decrypted. Use the app's value.")
    return notes


def doctor() -> int:
    """`python -m app.worker --doctor`: every check the worker depends on, with a pass/fail line each. No secrets printed."""
    bad = 0

    def line(ok: bool | None, text: str) -> None:
        nonlocal bad
        bad += ok is False
        print(f"[{'ok' if ok else 'FAIL' if ok is False else 'info'}] {text}")

    try:
        durable.init()
        line(True, f"database reachable ({durable.backend()}, id {queueing.db_fp()}); tables ready")
        for table in ("analysis_runs", "pack_runs", "workers", "run_artifacts"):
            durable.one(f"select 1 as x from {table} limit 1")
        c = queueing._counts()
        line(None, f"queued now: {c['analysis']['queued']} analyses, {c['pack']['queued']} pack runs; running: "
                   f"{c['analysis']['running'] + c['pack']['running']}")
    except Exception as exc:  # noqa: BLE001
        line(False, f"cannot use the database: {exc.__class__.__name__}. Check DATABASE_URL.")
    line(durable.IS_POSTGRES or None if durable.IS_POSTGRES else False,
         "DATABASE_URL points at Postgres" if durable.IS_POSTGRES else "DATABASE_URL is not set: this would use a local SQLite file, "
         "which the Vercel app can't see")
    line(bool(os.getenv("DSP_SECRET_KEY")), "DSP_SECRET_KEY is set" if os.getenv("DSP_SECRET_KEY") else "DSP_SECRET_KEY is not set (must equal the app's)")
    if blob.enabled():
        r = blob.check_remote()
        line(r["ok"], f"Blob: {r['message']}")
    else:
        line(False, "BLOB_READ_WRITE_TOKEN is not set: uploaded files can't be read")
    packs = sorted(p.name for p in config.PACKS_DIR.glob("*/analysis.py") for p in [p.parent]) if config.PACKS_DIR.exists() else []
    line(bool(packs), f"{len(packs)} starter packs found" if packs else f"no packs under {config.PACKS_DIR}")
    try:
        import duckdb  # noqa: F401
        import pandas  # noqa: F401
        line(True, "analysis dependencies import (pandas, duckdb)")
    except ImportError as exc:
        line(False, f"missing analysis dependency: {exc.name}")
    state = queueing.status()
    line(None, f"this app's view of workers: {state['state']} ({state['live']} live)")
    return 1 if bad else 0


def main() -> None:
    if "--doctor" in sys.argv:
        raise SystemExit(doctor())
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    name = os.getenv("DSP_WORKER_NAME") or f"{socket.gethostname()}-{os.getpid()}"
    poll = float(os.getenv("DSP_WORKER_POLL_SECONDS", "2"))
    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)
    durable.init()
    for note in startup_report(name):
        (log.warning if note.startswith("WARNING") else log.info)("%s", note)
    log.info("worker %s polling every %.1fs (%s)", name, poll, durable.backend())
    hb = Heartbeat(name)
    hb.start()
    while not _stop:
        try:
            if run_once(name, hb):
                hb.current = None
            else:
                time.sleep(poll)
        except Exception:  # noqa: BLE001 - one bad job never stops the worker
            log.exception("job failed outside the pipeline")
            hb.current = None
            time.sleep(poll)
    hb.halt.set()
    try:  # keep the row (current_run cleared): the app then reports "offline, last seen N s ago", not "never connected"
        queueing.beat(name, "all", None, started_at=hb.started)
    except Exception:  # noqa: BLE001
        pass
    log.info("worker %s stopped", name)


if __name__ == "__main__":
    main()
