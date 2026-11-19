"""Scheduled / on-demand provider imports.

Each source is fetched independently with its own timeout. A failure (timeout, auth change, outage)
records an error status for that source and leaves every indexed record searchable.
"""
from __future__ import annotations

import json
import os
import threading
import time

from . import store
from .adapters import cmr, kaggle, uci
from .adapters.http import AdapterError

ADAPTERS = {
    "uci": ("UCI Machine Learning Repository", uci.search),
    "kaggle": ("Kaggle", kaggle.search),
    "nasa-cmr": ("NASA Earthdata CMR", cmr.search),
}
QUERIES_FILE = store.CATALOG_DIR / "import_queries.json"
_running = threading.Event()
_last: dict = {}


def queries() -> dict:
    return json.loads(QUERIES_FILE.read_text(encoding="utf-8")) if QUERIES_FILE.exists() else {"max_per_query": 5}


def run(sources: list[str] | None = None, adapters: dict | None = None) -> dict:
    """Import from each source. `adapters` lets tests inject fakes."""
    if _running.is_set():
        return {"started": False, "reason": "An import is already running."}
    _running.set()
    started = time.monotonic()
    summary: dict = {}
    try:
        cfg = queries()
        table = adapters or ADAPTERS
        for source, (label, fn) in table.items():
            if sources and source not in sources:
                continue
            terms = cfg.get(source, [])
            if not terms:
                store.set_source_status(source, label, "skipped", "No import queries configured.")
                summary[source] = {"status": "skipped"}
                continue
            fetched, errors = [], []
            for term in terms:
                try:
                    fetched.extend(fn(term, cfg.get("max_per_query", 5)))
                except AdapterError as exc:
                    errors.append(f"'{term}': {exc}")
                    if "HTTP 401" in str(exc) or "HTTP 403" in str(exc) or "Timeout" in str(exc) or "URLError" in str(exc):
                        break  # the whole source is unavailable; don't hammer it
                except Exception as exc:  # malformed upstream data must not crash the import
                    errors.append(f"'{term}': unexpected {type(exc).__name__}: {exc}")
            result = store.upsert_imported(fetched) if fetched else {"added": 0, "updated": 0, "merged_into_reviewed": 0, "unchanged": 0}
            if errors and not fetched:
                store.set_source_status(source, label, "error", "; ".join(errors))
                summary[source] = {"status": "error", "errors": errors}
            else:
                detail = f"{len(fetched)} records fetched" + (f"; {len(errors)} query errors: {'; '.join(errors)}" if errors else "")
                count = sum(1 for r in store.all_records().values() if r["origin"] == "import" and _source_of(r) == source)
                store.set_source_status(source, label, "ok", detail, records=count)
                summary[source] = {"status": "ok", **result, "errors": errors}
    finally:
        _running.clear()
    _last.update({"summary": summary, "seconds": round(time.monotonic() - started, 1), "finished_at": store.now()})
    return {"started": True, **_last}


def _source_of(rec: dict) -> str:
    return {"UCI": "uci", "Kaggle": "kaggle", "NASA Earthdata (CMR)": "nasa-cmr"}.get(rec["provider"], rec["provider"])


def start_background(sources: list[str] | None = None) -> bool:
    if _running.is_set():
        return False
    threading.Thread(target=run, args=(sources,), daemon=True, name="catalog-import").start()
    return True


def status() -> dict:
    return {"running": _running.is_set(), "last": _last or None, "sources": store.source_statuses(),
            "configured": {k: v for k, v in queries().items() if k in ADAPTERS}}


def start_scheduler() -> None:
    """Refresh imports every DSP_IMPORT_INTERVAL_HOURS hours (0 = manual only, the default)."""
    hours = float(os.getenv("DSP_IMPORT_INTERVAL_HOURS", "0") or 0)
    if hours <= 0:
        return

    def loop():
        time.sleep(30)
        while True:
            run()
            time.sleep(hours * 3600)

    threading.Thread(target=loop, daemon=True, name="catalog-import-scheduler").start()
