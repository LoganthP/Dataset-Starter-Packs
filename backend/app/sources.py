"""Check that each pack's official source still responds (same logic as scripts/check_sources.py)."""
from __future__ import annotations

import datetime as dt
import json
import threading
import time
import urllib.error
import urllib.request

from . import catalog, config

STATE_FILE = config.STATE_DIR / "source_checks.json"
_lock = threading.Lock()
_running = False


def _probe(url: str, expect: list[str] | None, timeout: int = 25) -> dict:
    started = time.monotonic()
    req = urllib.request.Request(url, headers={"User-Agent": "dataset-starter-packs/0.1 source-check"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(400_000).decode("utf-8", errors="replace")
            status = resp.status
    except urllib.error.HTTPError as exc:
        return {"url": url, "ok": False, "status": exc.code, "ms": int((time.monotonic() - started) * 1000),
                "detail": f"HTTP {exc.code}"}
    except Exception as exc:  # DNS, TLS, timeout, proxy refusals
        return {"url": url, "ok": False, "status": None, "ms": int((time.monotonic() - started) * 1000),
                "detail": f"{type(exc).__name__}: {exc}"[:300]}
    missing = [t for t in (expect or []) if t not in body]
    return {"url": url, "ok": status < 400 and not missing, "status": status, "ms": int((time.monotonic() - started) * 1000),
            "detail": f"missing expected field(s): {', '.join(missing)}" if missing else "OK"}


def probe_link(url: str, kaggle: bool = False) -> dict:
    """Does a dataset's canonical page respond? Kaggle blocks scripted requests, so 403/404/429 there means 'check by hand'."""
    r = _probe(url, None)
    if kaggle and not r["ok"] and r["status"] in (403, 404, 429):
        return {**r, "ok": True, "detail": f"HTTP {r['status']} - Kaggle requires a signed-in browser; verify manually"}
    return r


def check_pack(meta: dict) -> dict:
    src = meta["source"]
    probes = []
    if src.get("health_check_url"):
        probes.append({"kind": "api query", **_probe(src["health_check_url"], src.get("health_check_expect"))})
    if src.get("access_method") == "direct-download":
        probes.append({"kind": "dataset page", **_probe(src["dataset_page"], None)})
    if src.get("access_method") == "kaggle":
        result = _probe(src["dataset_page"], None)
        # Kaggle often blocks scripted requests; treat it as a manual check rather than an outage.
        probes.append({"kind": "dataset page", **result, "ok": result["ok"] or result["status"] in (403, 404, 429),
                       "detail": result["detail"] + " (Kaggle requires a signed-in browser - verify manually)"})
    status = "ok" if all(p["ok"] for p in probes) else "error"
    if src.get("access_method") == "kaggle":
        status = "manual" if status == "ok" else status
    return {"slug": meta["slug"], "title": meta["title"], "provider": meta["provider"], "access_method": src.get("access_method"),
            "status": status, "probes": probes, "checked_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds")}


def run_all() -> None:
    global _running
    with _lock:
        if _running:
            return
        _running = True
    try:
        results = [check_pack(m) for m in catalog.list_packs() if "error" not in m]
        # Also check every reviewed or imported catalog record's canonical page.
        from .discovery import store as catalog_store
        for rec in catalog_store.all_records().values():
            r = probe_link(rec["canonicalUrl"], kaggle=rec["provider"] == "Kaggle")
            catalog_store.set_link_check(rec["id"], r["ok"], r["status"], r["detail"])
        STATE_FILE.write_text(json.dumps({"checked_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
                                          "results": results}, indent=2), encoding="utf-8")
    finally:
        _running = False


def start_background_check() -> bool:
    if _running:
        return False
    threading.Thread(target=run_all, daemon=True, name="source-check").start()
    return True


def latest() -> dict:
    data = json.loads(STATE_FILE.read_text(encoding="utf-8")) if STATE_FILE.exists() else {"checked_at": None, "results": []}
    data["running"] = _running
    return data
