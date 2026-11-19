"""Live provider search, one provider per request so the browser can show results as each one finishes.

Each provider call:
  * uses its own timeout (adapters/http.py) and never blocks the others,
  * is cached per (normalized query, provider) for DSP_LIVE_CACHE_HOURS (default 6),
  * indexes results into the catalog (origin "live", unreviewed) and records which query found them,
    so the normal /api/datasets search, filters and requirement checks apply to them unchanged.
"""
from __future__ import annotations

import datetime as dt
import os
import re
import time

from . import store
from .adapters import cmr, datacite, huggingface, kaggle, uci, web
from .adapters.http import AdapterError
from .vocab import STOPWORDS, parse_query

CACHE_HOURS = float(os.getenv("DSP_LIVE_CACHE_HOURS", "6"))

PROVIDERS: dict[str, dict] = {
    "huggingface": {"label": "Hugging Face", "fn": huggingface.search, "needs": None},
    "kaggle": {"label": "Kaggle", "fn": kaggle.search, "needs": None},
    "datacite": {"label": "DataCite (Zenodo, Figshare, Dryad…)", "fn": datacite.search, "needs": None},
    "uci": {"label": "UCI repository", "fn": uci.search, "needs": None},
    "nasa-cmr": {"label": "NASA Earthdata", "fn": cmr.search, "needs": None},
    "web": {"label": "Web search", "fn": web.search, "needs": "web"},
}


def topic_key(topic: str) -> str:
    """The cache/hit key for a topic: lowercased words, stopwords removed, order kept."""
    words = [w for w in re.findall(r"[a-z0-9][a-z0-9\-]+", (topic or "").lower()) if w not in STOPWORDS]
    return " ".join(dict.fromkeys(words))


def normalize_query(q: str, topic: str | None = None) -> str:
    return topic_key(topic if topic is not None else (parse_query(q).topic or q or ""))


def provider_list() -> list[dict]:
    out = []
    for key, p in PROVIDERS.items():
        configured = True
        note = None
        if p["needs"] == "web" and not web.engine():
            configured, note = False, "Add BRAVE_SEARCH_API_KEY (or GOOGLE_CSE_KEY + GOOGLE_CSE_CX) to backend/.env to enable."
        out.append({"key": key, "label": p["label"], "configured": configured, "note": note,
                    "engine": web.engine() if key == "web" else None})
    return out


def _attempts(topic: str) -> list[str]:
    """Full topic first; if a provider finds nothing, drop trailing words (project names, filler)."""
    words = topic.split()
    tries = [" ".join(words[:n]) for n in range(len(words), 0, -1)]
    return list(dict.fromkeys(t for t in tries if t))[:3]


def run(provider: str, q: str, refresh: bool = False, topic: str | None = None) -> dict:
    if provider not in PROVIDERS:
        raise KeyError(provider)
    query = normalize_query(q, topic)
    label = PROVIDERS[provider]["label"]
    if not query:
        return {"provider": provider, "label": label, "status": "skipped", "detail": "Type a topic to search live sources.", "count": 0, "ids": []}

    prev = store.live_run(query, provider)
    if prev and not refresh and prev["status"] == "ok":
        age_h = (dt.datetime.now(dt.UTC) - dt.datetime.fromisoformat(prev["fetched_at"])).total_seconds() / 3600
        if age_h < CACHE_HOURS:
            ids = [rid for rid, h in store.live_hits(query).items() if provider in h["providers"]]
            return {"provider": provider, "label": label, "status": "cached", "detail": f"Cached results from {prev['fetched_at']}",
                    "count": len(ids), "ms": 0, "fetched_at": prev["fetched_at"], "ids": ids}

    started = time.monotonic()
    fn = PROVIDERS[provider]["fn"]
    records, used, error = [], query, None
    try:
        for attempt in _attempts(query):
            used = attempt
            records = fn(attempt, 12)
            if records:
                break
    except web.NotConfigured as exc:
        return {"provider": provider, "label": label, "status": "not-configured", "detail": str(exc), "count": 0, "ids": []}
    except AdapterError as exc:
        error = str(exc)
    except Exception as exc:  # malformed upstream data: report, never crash the page
        error = f"Unexpected {type(exc).__name__}: {exc}"
    ms = int((time.monotonic() - started) * 1000)

    if error:
        store.record_live_run(query, provider, "error", error, 0, ms)
        cached = [rid for rid, h in store.live_hits(query).items() if provider in h["providers"]]
        return {"provider": provider, "label": label, "status": "error", "detail": error, "count": len(cached), "ms": ms,
                "ids": cached, "stale": bool(cached)}
    ids = store.upsert_live(records, provider, query)
    detail = f"{len(ids)} results" + (f" for '{used}'" if used != query else "")
    store.record_live_run(query, provider, "ok", detail, len(ids), ms)
    return {"provider": provider, "label": label, "status": "ok", "detail": detail, "count": len(ids), "ms": ms,
            "fetched_at": store.now(), "ids": ids}
