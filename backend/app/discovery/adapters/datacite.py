"""DataCite search: DOIs registered as datasets by Zenodo, Figshare, Dryad, Dataverse, ICPSR and others. No key needed.

    GET https://api.datacite.org/dois?query=<q>&resource-type-id=dataset&page[size]=<n>
        -> {data:[{id, attributes:{doi, titles[{title}], descriptions[{description}], publisher, publicationYear, url,
                    rightsList[{rights, rightsUri, rightsIdentifier}], formats[], sizes[], dates[{date, dateType}], subjects[{subject}],
                    geoLocations[], contentUrl}]}]}
"""
from __future__ import annotations

import re
import urllib.parse

from .common import commercial_use, slug
from .http import get_json

SEARCH_URL = "https://api.datacite.org/dois"
FORMAT_WORDS = {"csv": "csv", "text/csv": "csv", "json": "json", "application/json": "json", "parquet": "parquet", "xlsx": "xlsx",
                "netcdf": "netcdf", "application/x-netcdf": "netcdf", "tsv": "tsv", "zip": "zip"}


def _coverage(dates: list[dict]) -> dict:
    for d in dates or []:
        if (d.get("dateType") or "").lower() in ("collected", "coverage", "valid"):
            value = d.get("date") or ""
            parts = re.split(r"/", value)
            if parts and re.match(r"\d{4}", parts[0]):
                start = parts[0][:10]
                end = parts[1][:10] if len(parts) > 1 and re.match(r"\d{4}", parts[1]) else None
                return {"start": start if len(start) == 10 else f"{start[:4]}-01-01",
                        "end": (end if end and len(end) == 10 else (f"{end[:4]}-12-31" if end else None)),
                        "ongoing": False, "granularity": [], "status": "provider-reported", "note": f"DataCite '{d.get('dateType')}' date: {value}"}
    return {"status": "unknown", "note": "No 'Collected' date in the DOI metadata."}


def normalize(item: dict) -> dict | None:
    a = item.get("attributes") or {}
    doi = a.get("doi") or item.get("id")
    url = a.get("url") or (f"https://doi.org/{doi}" if doi else None)
    if not doi or not url or not url.startswith("http"):
        return None
    title = next((t.get("title") for t in a.get("titles") or [] if t.get("title")), None) or doi
    desc = next((d.get("description") for d in a.get("descriptions") or [] if d.get("description")), "") or "No description in the DOI metadata."
    rights = (a.get("rightsList") or [{}])[0] if a.get("rightsList") else {}
    lic = rights.get("rights") or rights.get("rightsIdentifier")
    fmts = sorted({FORMAT_WORDS[f.lower().strip()] for f in a.get("formats") or [] if f and f.lower().strip() in FORMAT_WORDS})
    publisher = a.get("publisher")
    publisher = publisher.get("name") if isinstance(publisher, dict) else publisher
    files = [{"url": a["contentUrl"][0] if isinstance(a.get("contentUrl"), list) else a["contentUrl"], "name": "contentUrl"}] if a.get("contentUrl") else []
    types = a.get("types") or {}
    raw_formats = " ".join(str(f).lower() for f in a.get("formats") or [])
    is_doc = ("documentation" in (types.get("resourceType") or "").lower() or (types.get("resourceTypeGeneral") or "") == "Text"
              or ("pdf" in raw_formats and not fmts))
    return {
        "kind": "documentation" if is_doc else "dataset",
        "id": "doi." + slug(doi.replace("/", "--")),
        "doi": doi.lower(),
        "title": " ".join(title.split())[:300],
        "description": re.sub(r"<[^>]+>", " ", " ".join(desc.split()))[:700],
        "publisher": f"{publisher or 'Unknown publisher'} (DOI via DataCite)",
        "provider": publisher or "DataCite",
        "providerId": doi,
        "canonicalUrl": url if url.startswith("https://") else url.replace("http://", "https://", 1),
        "sourceLinks": [{"label": "Dataset landing page", "url": url}, {"label": f"DOI {doi}", "url": f"https://doi.org/{doi}"}],
        "tags": sorted({(s.get("subject") or "").lower() for s in a.get("subjects") or [] if s.get("subject") and len(s["subject"]) < 60})[:12],
        "purposes": [],
        "characteristics": [],
        "formats": {"values": fmts, "status": "provider-reported" if fmts else "unknown", "evidence": f"https://api.datacite.org/dois/{doi}", "exhaustive": False},
        "access": {"method": "direct-download" if files else "unknown", "signInRequired": None, "status": "unknown",
                   "evidence": url, "note": "Open the landing page to see the files and any access conditions."},
        "license": {"name": lic, "url": rights.get("rightsUri"), "commercialUse": commercial_use(lic),
                    "status": "provider-reported" if lic else "unknown", "evidence": f"https://api.datacite.org/dois/{doi}"},
        "coverage": {"temporal": {**_coverage(a.get("dates")), "evidence": f"https://api.datacite.org/dois/{doi}"},
                     "spatial": {"scope": "unknown", "status": "unknown"}},
        "schemaStatus": "unknown",
        "fields": [],
        "files": files,
        "size": {"rows": None, "bytes": None, "note": ", ".join(a.get("sizes") or []) or None},
        "sourceUpdatedAt": (a.get("updated") or "")[:10] or None,
    }


def search(query: str, limit: int = 10) -> list[dict]:
    params = {"query": query, "resource-type-id": "dataset", "page[size]": limit, "sort": "relevance"}
    data = get_json(f"{SEARCH_URL}?{urllib.parse.urlencode(params)}")
    return [r for r in (normalize(i) for i in data.get("data", [])) if r]
