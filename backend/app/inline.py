"""Run small jobs inside the web app, with no separate worker.

On Vercel the API can't keep a background thread alive after it has replied, but it can keep a *request* alive. So after
queuing a run the browser calls POST .../drive; that request claims the run (atomically, like a worker would), executes it
within DSP_INLINE_BUDGET_SECONDS and returns when it is done, while the Run view keeps polling for progress as usual.

  * Starter packs in sample mode, and analyses, run here. Pack runs in real-data mode download into the pack folder, which is
    read-only on Vercel, so they stay queued for a worker.
  * If a dedicated worker is connected it gets the job instead (this returns {"driver": "worker"}).
  * The request keeps a heartbeat row (kind "inline") so the stale-worker reaper doesn't take the run back while it executes.
    If the platform kills the function, the reaper requeues it (once), and the next page view drives it again.
"""
from __future__ import annotations

import logging
import socket
import uuid

from . import config, db, queueing, runner
from .discovery import analysis

log = logging.getLogger("dsp.inline")


def enabled() -> bool:
    return config.RUN_MODE == "queue" and config.INLINE_RUNS


def pack_eligible(run: dict) -> bool:
    return enabled() and run.get("mode") == "sample"


def analysis_eligible(run: dict) -> bool:
    return enabled() and bool(run.get("job") or run.get("status") == "queued")


def _dedicated_worker_live() -> bool:
    return any(w["live"] for w in queueing.workers(inline=False))


def _name() -> str:
    return f"inline-{socket.gethostname()[:12]}-{uuid.uuid4().hex[:6]}"


def drive_pack(run_id: str) -> dict:
    run = db.get(run_id)
    if not run:
        return {"driver": "none", "status": "missing"}
    if run["status"] != "queued":
        return {"driver": "none", "status": run["status"]}
    if not pack_eligible(run):
        return {"driver": "worker", "status": "queued", "reason": "needs a worker"}
    if _dedicated_worker_live():
        return {"driver": "worker", "status": "queued"}
    name = _name()
    claimed = db.claim(run_id, name, queueing._iso())
    if not claimed:
        return {"driver": "none", "status": (db.get(run_id) or {}).get("status", "missing")}
    hb = queueing.Heartbeat(name, queueing.INLINE_KIND)
    hb.current = run_id
    hb.start()
    try:
        runner.execute_claimed(claimed, timeout=config.INLINE_BUDGET_SECONDS)
    finally:
        hb.halt.set()
        queueing.forget(name)
    return {"driver": "inline", "status": (db.get(run_id) or {}).get("status")}


def drive_analysis(run_id: str) -> dict:
    run = analysis.get(run_id, user=analysis.ANY)
    if not run:
        return {"driver": "none", "status": "missing"}
    if run["status"] != "queued" or not run.get("job"):
        return {"driver": "none", "status": run["status"]}
    if not analysis_eligible(run):
        return {"driver": "worker", "status": "queued"}
    if _dedicated_worker_live():
        return {"driver": "worker", "status": "queued"}
    name = _name()
    claimed = analysis.claim(run_id, name)
    if not claimed:
        return {"driver": "none", "status": (analysis.get(run_id, user=analysis.ANY) or {}).get("status", "missing")}
    job = claimed.get("job") or {}
    hb = queueing.Heartbeat(name, queueing.INLINE_KIND)
    hb.current = run_id
    hb.start()
    try:
        analysis._execute(run_id, job["rec"], job.get("fetch"), None, job.get("mode") or "sample", budget=config.INLINE_BUDGET_SECONDS)
        analysis._update(run_id, job=None)
        done = analysis.get(run_id, user=analysis.ANY) or {}
        if done.get("status") == "failed" and done.get("error_kind") == "timeout":
            analysis._update(run_id, error=f"{done.get('error')} The site itself can run for about {int(config.INLINE_BUDGET_SECONDS)} s; "
                                           "large runs need a worker (`python -m app.worker`) or a smaller sample.")
    finally:
        hb.halt.set()
        queueing.forget(name)
    return {"driver": "inline", "status": (analysis.get(run_id, user=analysis.ANY) or {}).get("status")}
