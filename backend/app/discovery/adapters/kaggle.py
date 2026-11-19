"""Kaggle adapter: the official dataset list/search endpoint, called server-side.

    GET https://www.kaggle.com/api/v1/datasets/list?search=<q>&page=1  -> [ {ref, title, subtitle, ownerName,
         licenseName, totalBytes, lastUpdated, tags, ...} ]

Credentials (optional, never sent to the browser): KAGGLE_USERNAME + KAGGLE_KEY env vars, or
~/.kaggle/kaggle.json. Kaggle search results carry no column schema or observation period, so those
stay "unknown"; every Kaggle download needs a signed-in account.
"""
from __future__ import annotations

import base64
import json
import os
import re
import urllib.parse
from pathlib import Path

from .http import get_json

LIST_URL = "https://www.kaggle.com/api/v1/datasets/list"
ALLOWED = ("cc0", "public domain", "cc by 4.0", "cc-by", "attribution 4.0", "cc by-sa", "odbl", "open database", "mit", "apache", "open government")


def _auth_header() -> dict:
    user, key = os.getenv("KAGGLE_USERNAME"), os.getenv("KAGGLE_KEY")
    if not (user and key):
        cfg = Path.home() / ".kaggle" / "kaggle.json"
        if cfg.exists():
            try:
                data = json.loads(cfg.read_text())
                user, key = data.get("username"), data.get("key")
            except (OSError, json.JSONDecodeError):
                pass
    if user and key:
        return {"Authorization": "Basic " + base64.b64encode(f"{user}:{key}".encode()).decode()}
    return {}


def commercial_use(license_name: str | None) -> str:
    name = (license_name or "").lower()
    if not name or name in ("unknown", "other", "other (specified in description)"):
        return "unknown"
    tokens = set(re.split(r"[^a-z0-9]+", name))
    if "nc" in tokens or "non-commercial" in name or "noncommercial" in name:
        return "not-allowed"
    if any(tok in name for tok in ALLOWED):
        return "allowed"
    return "unknown"


def normalize(item: dict) -> dict:
    ref = item["ref"]
    url = f"https://www.kaggle.com/datasets/{ref}"
    tags = [t.get("name") if isinstance(t, dict) else str(t) for t in item.get("tags") or []]
    lic = item.get("licenseName")
    return {
        "id": "kaggle." + ref.lower().replace("/", "-"),
        "title": item.get("title") or ref,
        "description": (item.get("subtitle") or "No subtitle provided on Kaggle.").strip(),
        "publisher": f"{item.get('ownerName') or ref.split('/')[0]} (via Kaggle)",
        "provider": "Kaggle",
        "providerId": ref,
        "canonicalUrl": url,
        "sourceLinks": [{"label": "Kaggle dataset page", "url": url}],
        "tags": sorted({t.lower() for t in tags if t}),
        "purposes": [],
        "characteristics": [],
        "formats": {"values": [], "status": "unknown", "note": "Kaggle search results don't list file formats."},
        "access": {"method": "sign-in", "signInRequired": True, "status": "provider-reported", "evidence": url},
        "license": {"name": lic or None, "url": url, "commercialUse": commercial_use(lic),
                    "status": "provider-reported" if lic else "unknown", "evidence": url},
        "coverage": {"temporal": {"status": "unknown"}, "spatial": {"scope": "unknown", "status": "unknown"}},
        "schemaStatus": "unknown",
        "fields": [],
        "size": {"rows": None, "bytes": item.get("totalBytes")},
        "limitations": [],
        "sourceUpdatedAt": (item.get("lastUpdated") or "")[:10] or None,
    }


def search(query: str, limit: int = 8) -> list[dict]:
    data = get_json(f"{LIST_URL}?{urllib.parse.urlencode({'search': query, 'page': 1})}", headers=_auth_header())
    items = data if isinstance(data, list) else data.get("datasets", [])
    return [normalize(i) for i in items[:limit] if i.get("ref")]
