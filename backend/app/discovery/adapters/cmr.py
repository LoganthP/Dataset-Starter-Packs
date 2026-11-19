"""NASA Earthdata CMR adapter (Earth science collections; no key needed for search).

    GET https://cmr.earthdata.nasa.gov/search/collections.umm_json?keyword=<q>&page_size=<n>
        -> {hits, items:[{meta:{concept-id, provider-id, revision-date}, umm:{EntryTitle, Abstract, TemporalExtents,
             SpatialExtent, DataCenters, ArchiveAndDistributionInformation, RelatedUrls, DOI, UseConstraints, ...}}]}

NASA POWER and the Exoplanet Archive are separate sources in the catalog (curated packs), not CMR imports.
"""
from __future__ import annotations

import urllib.parse

from .http import get_json

SEARCH_URL = "https://cmr.earthdata.nasa.gov/search/collections.umm_json"
FORMAT_MAP = {"netcdf": "netcdf", "netcdf-4": "netcdf", "netcdf4": "netcdf", "hdf5": "hdf5", "hdf-eos5": "hdf5", "csv": "csv",
              "ascii": "csv", "geotiff": "geotiff", "cog": "geotiff", "json": "json", "parquet": "parquet"}


def _formats(umm: dict) -> list[str]:
    out = set()
    for f in (umm.get("ArchiveAndDistributionInformation") or {}).get("FileDistributionInformation", []) or []:
        key = (f.get("Format") or "").strip().lower()
        out.add(FORMAT_MAP.get(key, key))
    return sorted(x for x in out if x)


def _temporal(umm: dict) -> dict:
    for ext in umm.get("TemporalExtents") or []:
        for rng in ext.get("RangeDateTimes") or []:
            return {"start": (rng.get("BeginningDateTime") or "")[:10] or None, "end": (rng.get("EndingDateTime") or "")[:10] or None,
                    "ongoing": bool(ext.get("EndsAtPresentFlag")), "granularity": [], "status": "provider-reported"}
    return {"status": "unknown"}


def _spatial(umm: dict) -> dict:
    geo = ((umm.get("SpatialExtent") or {}).get("HorizontalSpatialDomain") or {}).get("Geometry") or {}
    for box in geo.get("BoundingRectangles") or []:
        w, e, n, s = box.get("WestBoundingCoordinate"), box.get("EastBoundingCoordinate"), box.get("NorthBoundingCoordinate"), box.get("SouthBoundingCoordinate")
        if None not in (w, e, n, s):
            if w <= -179 and e >= 179 and n >= 80 and s <= -80:
                return {"scope": "global-grid", "regions": ["global"], "description": "Global", "status": "provider-reported"}
            return {"scope": "bounding-box", "regions": [], "description": f"Bounding box W{w} E{e} S{s} N{n}", "status": "provider-reported"}
    return {"scope": "unknown", "status": "unknown"}


def normalize(item: dict) -> dict:
    meta, umm = item.get("meta", {}), item.get("umm", {})
    cid = meta["concept-id"]
    landing = next((u.get("URL") for u in umm.get("RelatedUrls") or [] if u.get("Type") == "DATA SET LANDING PAGE" and u.get("URL", "").startswith("https://")), None)
    concept_url = f"https://cmr.earthdata.nasa.gov/search/concepts/{cid}.html"
    canonical = landing or concept_url
    meta_url = f"{SEARCH_URL}?concept_id={cid}"
    tags = set()
    for kw in umm.get("ScienceKeywords") or []:
        for k in ("Term", "VariableLevel1"):
            if kw.get(k):
                tags.add(kw[k].lower())
    centers = [d.get("ShortName") for d in umm.get("DataCenters") or [] if d.get("ShortName")]
    doi = (umm.get("DOI") or {}).get("DOI")
    links = [{"label": "Landing page", "url": canonical}, {"label": "CMR metadata", "url": meta_url}]
    if doi:
        links.append({"label": f"DOI {doi}", "url": f"https://doi.org/{doi}"})
    fmts = _formats(umm)
    temporal = _temporal(umm)
    return {
        "id": "nasa-cmr." + cid.lower(),
        "title": umm.get("EntryTitle") or umm.get("ShortName") or cid,
        "description": ((umm.get("Abstract") or "No abstract.").strip())[:600],
        "publisher": centers[0] if centers else "NASA Earthdata",
        "provider": "NASA Earthdata (CMR)",
        "providerId": cid,
        "canonicalUrl": canonical,
        "sourceLinks": links,
        "tags": sorted(tags)[:15],
        "purposes": ["exploratory"],
        "characteristics": ["geospatial", "time-series"] if temporal.get("start") else ["geospatial"],
        "formats": {"values": fmts, "status": "provider-reported" if fmts else "unknown", "evidence": meta_url},
        "access": {"method": "direct-download", "signInRequired": None, "status": "unknown", "evidence": canonical,
                   "note": "Many NASA archives require a free Earthdata Login; check the landing page."},
        "license": {"name": "See UseConstraints / data use guidance", "url": canonical, "commercialUse": "unknown", "status": "unknown", "evidence": meta_url},
        "coverage": {"temporal": {**temporal, "evidence": meta_url}, "spatial": {**_spatial(umm), "evidence": meta_url}},
        "schemaStatus": "unknown",
        "fields": [],
        "size": {"rows": None, "bytes": None},
        "limitations": [],
        "sourceUpdatedAt": (meta.get("revision-date") or "")[:10] or None,
    }


def search(query: str, limit: int = 8) -> list[dict]:
    data = get_json(f"{SEARCH_URL}?{urllib.parse.urlencode({'keyword': query, 'page_size': limit})}")
    return [normalize(i) for i in data.get("items", []) if i.get("meta", {}).get("concept-id")]
