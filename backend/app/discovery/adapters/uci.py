"""UCI Machine Learning Repository adapter (same public API the official `ucimlrepo` package uses).

    list:    https://archive.ics.uci.edu/api/datasets/list?filter=python&search=<q>  -> {status, data:[{id, name}]}
    dataset: https://archive.ics.uci.edu/api/dataset?id=<id>                         -> {status, data:{...metadata, variables}}

UCI's API carries a full variable list, so the schema is marked complete. It does not carry the license
or the observation period, so those stay "unknown" until a reviewer adds them to a seed record.
"""
from __future__ import annotations

import datetime as dt
import re
import urllib.parse

from .http import AdapterError, get_json

LIST_URL = "https://archive.ics.uci.edu/api/datasets/list"
DATASET_URL = "https://archive.ics.uci.edu/api/dataset"
LATLON = re.compile(r"^(lat|latitude|lon|lng|long|longitude)$|(^|_)(lat|lon|lng)(_|$)", re.I)
CHAR_MAP = {"tabular": "tabular", "multivariate": "tabular", "time-series": "time-series", "sequential": "time-series",
            "image": "image", "text": "text", "spatiotemporal": "geospatial", "spatial": "geospatial"}
TASK_MAP = {"classification": "classification", "regression": "regression", "clustering": "exploratory"}


def _date(s: str | None) -> str | None:
    for fmt in ("%a %b %d %Y", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime((s or "")[:15].strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


def normalize(meta: dict) -> dict:
    uid = meta["uci_id"]
    api = f"{DATASET_URL}?id={uid}"
    page = meta.get("repository_url") or f"https://archive.ics.uci.edu/dataset/{uid}"
    fields = []
    for v in meta.get("variables") or []:
        concepts = []
        if (v.get("type") or "").lower() in ("date", "datetime"):
            concepts.append("timestamp")
        if (v.get("role") or "").lower() == "target":
            concepts.append("target_label")
        if (v.get("role") or "").lower() == "id":
            concepts.append("join_key")
        if LATLON.search(v.get("name") or ""):
            concepts.append("latlon")
        fields.append({"name": v.get("name") or "?", "type": v.get("type"), "unit": v.get("units") or None,
                       "description": v.get("description") or "", "concepts": concepts, "level": "record",
                       "status": "provider-reported", "evidence": api})
    chars = sorted({CHAR_MAP[c.strip().lower()] for c in (meta.get("characteristics") or []) if c.strip().lower() in CHAR_MAP})
    tasks = meta.get("tasks") or meta.get("task") or []
    tasks = tasks if isinstance(tasks, list) else [tasks]
    purposes = sorted({TASK_MAP[t.strip().lower()] for t in tasks if isinstance(t, str) and t.strip().lower() in TASK_MAP})
    if "time-series" in chars and "regression" in purposes:
        purposes.append("forecasting")
    return {
        "id": f"uci.{uid}",
        "title": meta.get("name") or f"UCI dataset {uid}",
        "description": (meta.get("abstract") or "No abstract provided.").strip(),
        "publisher": "UCI Machine Learning Repository",
        "provider": "UCI",
        "providerId": str(uid),
        "canonicalUrl": page,
        "sourceLinks": [{"label": "UCI dataset page", "url": page}, {"label": "UCI API metadata", "url": api}],
        "tags": sorted({t.lower() for t in [meta.get("area") or "", *(meta.get("characteristics") or [])] if t}),
        "purposes": purposes,
        "characteristics": chars,
        "formats": {"values": ["csv"] if meta.get("data_url") else [], "status": "provider-reported" if meta.get("data_url") else "unknown", "evidence": api},
        "access": {"method": "direct-download", "signInRequired": False, "status": "provider-reported", "evidence": api},
        "license": {"name": None, "url": page, "commercialUse": "unknown", "status": "unknown", "evidence": page,
                    "note": "UCI's API doesn't include the license. Most UCI pages state CC BY 4.0, but check this one."},
        "coverage": {"temporal": {"status": "unknown", "note": "Not in UCI's structured metadata; read the dataset summary."},
                     "spatial": {"scope": "unknown", "status": "unknown"}},
        "schemaStatus": "complete" if fields else "unknown",
        "fields": fields,
        "size": {"rows": meta.get("num_instances"), "bytes": None},
        "limitations": [],
        "sourceUpdatedAt": _date(meta.get("last_updated")),
    }


def search(query: str, limit: int = 8) -> list[dict]:
    listing = get_json(f"{LIST_URL}?{urllib.parse.urlencode({'filter': 'python', 'search': query.lower()})}")
    if listing.get("status") != 200:
        raise AdapterError(f"UCI list returned status {listing.get('status')}")
    out = []
    for entry in (listing.get("data") or [])[:limit]:
        detail = get_json(f"{DATASET_URL}?id={entry['id']}")
        if detail.get("status") == 200 and detail.get("data"):
            out.append(normalize(detail["data"]))
    return out
