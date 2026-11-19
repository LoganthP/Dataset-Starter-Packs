"""Search = full-text relevance (FTS5/BM25) + plain filters + evidence-based requirement checks.

Order of operations:
1. Topic words (expanded with synonyms) select candidates by FTS; no topic means every record.
2. Plain filters narrow candidates. AND across groups, OR within a group.
3. Requirements (fields, coverage, format, region, resolution, commercial reuse) are evaluated from
   stored evidence for every candidate and decide its group *before* ranking:
   meets -> needs-verification -> does-not-meet. A record with an unconfirmed required field can
   therefore never appear as a confirmed match, however relevant its text is.
4. Within a group, rank by relevance plus small evidence/curation signals.
Facet counts for a group are computed with every other group's filters applied.
"""
from __future__ import annotations

import datetime as dt
from collections import Counter

from . import store
from .fit import coverage_years, evaluate, span_text
from .vocab import CONCEPT_LABELS, Criteria, expand_topic, parse_query, region_label

FIT_ORDER = {"meets": 0, "needs-verification": 1, "does-not-meet": 2}
PURPOSES = ["forecasting", "classification", "regression", "geospatial", "sql-analytics", "exploratory"]
KINDS = ["tabular", "time-series", "geospatial", "relational", "gridded", "image", "text"]
FORMATS = ["csv", "json", "parquet", "xlsx", "netcdf"]
ACCESS = ["direct-download", "api", "sign-in", "unknown"]
LICENSE_CLASSES = ["commercial-ok", "conditional", "non-commercial", "unknown"]
DIFFICULTY = ["beginner", "intermediate", "advanced"]
READINESS = ["starter-pack", "analyzed", "notebook", "offline-sample"]


def _csv(v) -> list[str]:
    if v is None:
        return []
    if isinstance(v, list):
        items = [x for part in v for x in str(part).split(",")]
    else:
        items = str(v).split(",")
    return [i.strip() for i in items if i.strip()]


def _flag(v) -> bool:
    return str(v).lower() in ("1", "true", "yes", "on")


def criteria_from_params(p: dict) -> Criteria:
    """Explicit URL params are the criteria. `topic` overrides the topic parsed from q."""
    parsed = parse_query(p.get("q", ""))
    c = Criteria(topic=p["topic"] if "topic" in p else parsed.topic)
    c.fields = [f for f in _csv(p.get("fields")) if f in CONCEPT_LABELS]
    try:
        c.min_years = float(p["min_years"]) if p.get("min_years") not in (None, "") else None
    except ValueError:
        c.min_years = None
    c.formats = [f.lower() for f in _csv(p.get("formats"))]
    c.region = p.get("region") or None
    c.granularity = p.get("granularity") or None
    c.commercial = _flag(p.get("commercial"))
    c.soft = _csv(p.get("soft"))
    c.purposes = _csv(p.get("purpose"))
    c.difficulty = _csv(p.get("difficulty"))
    c.offline = _flag(p.get("offline"))
    c.notebook = _flag(p.get("notebook"))
    return c


def access_class(r: dict) -> str:
    a = r.get("access", {})
    if a.get("signInRequired"):
        return "sign-in"
    return a.get("method") if a.get("method") in ("direct-download", "api") else "unknown"


def license_class(r: dict) -> str:
    return {"allowed": "commercial-ok", "not-allowed": "non-commercial", "conditional": "conditional"}.get(
        r.get("license", {}).get("commercialUse"), "unknown")


def readiness(r: dict) -> set[str]:
    cur = r.get("curated") or {}
    out = set()
    if cur:
        out.add("starter-pack")
    if r.get("analysis"):
        out.add("analyzed")
    if cur.get("notebook"):
        out.add("notebook")
    if cur.get("offlineSample"):
        out.add("offline-sample")
    return out


ANALYZABLE_FORMATS = {"csv", "tsv", "parquet", "json", "jsonl", "xlsx", "zip", "sinex", "snx", "sinex-gz", "sinex-z"}
FORMAT_NAMES = {"netcdf": "NetCDF", "nc": "NetCDF", "hdf5": "HDF5", "hdf": "HDF", "h5": "HDF5", "grib": "GRIB", "pdf": "PDF",
                "shp": "Shapefile", "geotiff": "GeoTIFF", "tif": "GeoTIFF", "xls": "Excel 97 (.xls)", "7z": "7-Zip", "rar": "RAR",
                "docx": "Word", "txt": "plain text", "api": "API only"}


def unsupported_formats(r: dict, files: list[dict] | None = None) -> list[str]:
    """Format names the app can't analyze yet, when nothing analyzable is listed (e.g. NetCDF from NASA CMR)."""
    if files and any(f.get("supported") for f in files):
        return []
    fmts = {str(f.get("format") or "").lower() for f in files or []} | {str(v).lower() for v in (r.get("formats") or {}).get("values", [])}
    fmts = {f for f in fmts if f and f not in ANALYZABLE_FORMATS and f not in ("unknown", "other", "html")}
    return sorted({FORMAT_NAMES.get(f, f.upper()) for f in fmts})


def runnable(r: dict) -> str:
    """What a card can offer before any job: sample | kaggle | sign-in | unsupported | documentation."""
    if r.get("kind") == "documentation":
        return "documentation"
    if r.get("provider") == "Kaggle":
        return "kaggle"  # fetched inside the app once the user connects a Kaggle account
    if (r.get("access") or {}).get("signInRequired"):
        return "sign-in"
    vals = {str(v).lower() for v in (r.get("formats") or {}).get("values", [])}
    if vals and not vals & ANALYZABLE_FORMATS and unsupported_formats(r):
        return "unsupported"
    return "sample"


def analyzable(r: dict) -> bool:
    """The Analyze action is offered on every result: files are resolved from the provider on demand (resolve.py),
    and when none can be fetched directly the user can upload one. Documentation records too (the data may be linked)."""
    return True


def _date(s):
    try:
        return dt.date.fromisoformat(s[:10]) if s else None
    except ValueError:
        return None


def summarize(r: dict, link: dict | None = None) -> dict:
    """Compact row payload (no full field list)."""
    t = r.get("coverage", {}).get("temporal", {})
    s = r.get("coverage", {}).get("spatial", {})
    return {
        "id": r["id"], "title": r["title"], "description": r["description"], "publisher": r["publisher"],
        "provider": r["provider"], "providerId": r["providerId"], "canonicalUrl": r["canonicalUrl"],
        "formats": r.get("formats", {}), "access": {**r.get("access", {}), "class": access_class(r)},
        "license": {**r.get("license", {}), "class": license_class(r)},
        "coverage": {
            "temporal": {**t, "text": span_text(t) if t.get("start") else ("Not a time series" if "static" in t.get("granularity", []) else "Unknown"),
                         "years": coverage_years(t)},
            "spatial": {**s, "text": s.get("description") or ", ".join(region_label(x) for x in s.get("regions", [])) or "Unknown"},
        },
        "purposes": r.get("purposes", []), "characteristics": r.get("characteristics", []), "tags": r.get("tags", []),
        "fieldNames": [f["name"] for f in r.get("fields", [])], "schemaStatus": r.get("schemaStatus"),
        "size": r.get("size", {}), "curated": r.get("curated"), "packId": r.get("packId"),
        "origin": r["origin"], "reviewStatus": r.get("reviewStatus"), "stale": r.get("stale", False),
        "unitOfAnalysis": r.get("unitOfAnalysis"), "kind": r.get("kind", "dataset"), "analysis": r.get("analysis"),
        "analyzable": analyzable(r), "runnable": runnable(r), "unsupportedFormats": unsupported_formats(r), "readiness": sorted(readiness(r)), "doi": r.get("doi"), "configs": r.get("configs", []),
        "files": r.get("files", []), "previewProvider": r.get("previewProvider"), "verifiedImport": r.get("verifiedImport"),
        "sourceUpdatedAt": r.get("sourceUpdatedAt"), "lastVerifiedAt": r.get("lastVerifiedAt"), "lastFetchedAt": r.get("lastFetchedAt"),
        "linkCheck": link,
    }


def search(p: dict) -> dict:
    c = criteria_from_params(p)
    scope = p.get("scope", "all")
    sort = p.get("sort", "fit")
    page = max(1, int(p.get("page", 1) or 1))
    page_size = min(50, max(1, int(p.get("page_size", 20) or 20)))
    include_failed = _flag(p.get("include_failed"))
    period = (p.get("period_from") or None, p.get("period_to") or None)
    max_mb = float(p["max_mb"]) if p.get("max_mb") not in (None, "") else None
    max_minutes = int(p["max_minutes"]) if p.get("max_minutes") not in (None, "") else None

    terms = expand_topic(c.topic)
    scores = store.fts_scores(terms) if terms else None
    from .live import topic_key  # local import: live imports adapters

    hits = store.live_hits(topic_key(c.topic)) if c.topic else {}
    if scores is not None:
        for rid, h in hits.items():  # provider rank becomes relevance for records the provider matched
            scores[rid] = scores.get(rid, 0.0) + 8.0 / (1 + h["rank"])
    records = _with_analysis(store.all_records())
    links = store.link_checks()
    candidates = [r for r in records.values() if scores is None or r["id"] in scores]
    if scope == "curated":  # starter packs and successfully analyzed datasets
        candidates = [r for r in candidates if r.get("curated") or r.get("analysis")]

    filters = {
        "provider": (set(_csv(p.get("provider"))), lambda r: {r["provider"]}),
        "purpose": (set(c.purposes), lambda r: set(r.get("purposes", []))),
        "kind": (set(_csv(p.get("kind"))), lambda r: set(r.get("characteristics", []))),
        "access": (set(_csv(p.get("access"))), lambda r: {access_class(r)}),
        "license": (set(_csv(p.get("license"))), lambda r: {license_class(r)}),
        "difficulty": (set(c.difficulty), lambda r: {(r.get("curated") or {}).get("difficulty")} - {None}),
    }
    ready_param = set(_csv(p.get("ready")))
    badge_any = ready_param & {"starter-pack", "analyzed"}  # OR: either badge
    readiness_req = {k for k, on in (("notebook", c.notebook), ("offline-sample", c.offline)) if on} | (ready_param - badge_any)

    def passes(r: dict, skip: str | None = None) -> bool:
        for group, (wanted, values) in filters.items():
            if group != skip and wanted and not (wanted & values(r)):
                return False
        if skip != "ready" and readiness_req and not readiness_req <= readiness(r):
            return False
        if skip != "ready" and badge_any and not badge_any & readiness(r):
            return False
        if max_mb is not None and (r.get("size") or {}).get("bytes") and r["size"]["bytes"] > max_mb * 1e6:
            return False
        if max_minutes is not None:
            mins = (r.get("curated") or {}).get("estimatedMinutes")
            if mins is None or mins > max_minutes:
                return False
        return True

    evaluated = {r["id"]: evaluate(r, c, period) for r in candidates}

    facets: dict[str, list[dict]] = {}
    for group, (_, values) in filters.items():
        counter: Counter = Counter()
        for r in candidates:
            if passes(r, skip=group):
                counter.update(values(r))
        options = {"purpose": PURPOSES, "kind": KINDS, "access": ACCESS, "license": LICENSE_CLASSES, "difficulty": DIFFICULTY}.get(group)
        if options is None:  # provider: every provider among the candidates, busiest first
            seen = {v for r in candidates for v in values(r)} | filters[group][0]
            keys = sorted(seen, key=lambda k: (-counter.get(k, 0), k))
            facets[group] = [{"value": k, "count": counter.get(k, 0)} for k in keys]
        else:
            facets[group] = [{"value": k, "count": counter.get(k, 0)} for k in options if counter.get(k, 0) or k in filters[group][0]]
    ready_counter: Counter = Counter()
    for r in candidates:
        if passes(r, skip="ready"):
            ready_counter.update(readiness(r))
    facets["ready"] = [{"value": k, "count": ready_counter.get(k, 0)} for k in READINESS]

    passing = [r for r in candidates if passes(r)]
    fit_counts = Counter(evaluated[r["id"]]["fit"] for r in passing)

    def rank(r: dict) -> tuple:
        ev = evaluated[r["id"]]
        rel = scores.get(r["id"], 0.0) if scores else 0.0
        met_soft = sum(1 for x in ev["reasons"] if not x["required"] and x["outcome"] == "met")
        signal = rel + 0.6 * met_soft + (0.4 if r.get("reviewStatus") == "reviewed" else 0) + (0.3 if r.get("curated") else 0)
        if sort == "relevance":
            return (-signal, r["title"])
        if sort == "updated":
            d = _date(r.get("sourceUpdatedAt")) or dt.date.min
            return (FIT_ORDER[ev["fit"]], -d.toordinal(), r["title"])
        if sort == "title":
            return (r["title"].lower(),)
        return (FIT_ORDER[ev["fit"]], -signal, r["title"])

    ordered = sorted(passing, key=rank)
    if not include_failed:
        ordered = [r for r in ordered if evaluated[r["id"]]["fit"] != "does-not-meet"]
    total = len(ordered)
    window = ordered[(page - 1) * page_size: page * page_size]
    items = [{**summarize(r, links.get(r["id"])), **evaluated[r["id"]],
              "relevance": round(scores.get(r["id"], 0.0), 3) if scores else None,
              "liveHit": hits.get(r["id"])} for r in window]

    return {
        "criteria": {**c.to_dict(), "period_from": period[0], "period_to": period[1]},
        "terms": terms,
        "scope": scope,
        "sort": sort,
        "page": page,
        "page_size": page_size,
        "total": total,
        "catalogSize": len(records),
        "counts": {"meets": fit_counts.get("meets", 0), "needs-verification": fit_counts.get("needs-verification", 0),
                   "does-not-meet": fit_counts.get("does-not-meet", 0), "candidates": len(candidates)},
        "facets": facets,
        "items": items,
    }


def _with_analysis(records: dict[str, dict]) -> dict[str, dict]:
    from .analysis import latest_successful

    latest = latest_successful()
    if not latest:
        return records
    return {k: ({**v, "analysis": latest[k]} if k in latest else v) for k, v in records.items()}


def detail(record_id: str, p: dict) -> dict | None:
    r = _with_analysis(store.all_records()).get(record_id)
    if not r:
        return None
    c = criteria_from_params(p)
    period = (p.get("period_from") or None, p.get("period_to") or None)
    link = store.link_checks().get(record_id)
    return {**summarize(r, link), "fields": r.get("fields", []), "sourceLinks": r.get("sourceLinks", []),
            "limitations": r.get("limitations", []), **evaluate(r, c, period)}
