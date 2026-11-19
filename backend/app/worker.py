"""Analysis worker for queue mode (DSP_RUN_MODE=queue).

The API records each job in analysis_runs (status=queued, job=...). This process claims jobs one at a time
with an atomic UPDATE and runs them with the same pipeline, so progress, cancellation and reports appear in
the existing Run view. Run it where there is disk and time for 2 GB transfers and long analyses:

    python -m app.worker                      # from backend/, sharing DATABASE_URL (and BLOB_READ_WRITE_TOKEN)
    docker compose --profile worker up        # the compose service

Uploads in queue mode go to private object storage (Vercel Blob), never to the API's local disk.
"""
from __future__ import annotations

import logging
import os
import signal
import socket
import time

from . import durable
from .discovery import analysis

log = logging.getLogger("dsp.worker")
_stop = False


def _handle(signum, frame) -> None:  # noqa: ARG001
    global _stop
    _stop = True


def run_once(name: str) -> bool:
    run = analysis.claim_next(name)
    if not run:
        return False
    job = run.get("job") or {}
    log.info("running %s (%s)", run["id"], run["dataset_id"])
    analysis._execute(run["id"], job["rec"], job.get("fetch"), None, job.get("mode") or run.get("mode") or "sample")
    durable.execute("update analysis_runs set job=null where id=?", (run["id"],))  # the job payload isn't needed after it ran
    return True


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    name = os.getenv("DSP_WORKER_NAME") or f"{socket.gethostname()}-{os.getpid()}"
    poll = float(os.getenv("DSP_WORKER_POLL_SECONDS", "2"))
    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)
    durable.init()
    log.info("worker %s polling every %.1fs (%s)", name, poll, durable.backend())
    while not _stop:
        try:
            if not run_once(name):
                time.sleep(poll)
        except Exception:  # noqa: BLE001 - one bad job never stops the worker
            log.exception("job failed outside the pipeline")
            time.sleep(poll)


if __name__ == "__main__":
    main()
