"""Web search for dataset landing pages, then enrichment from schema.org/Dataset JSON-LD where pages publish it.

Configure one engine (keys stay server-side):
    BRAVE_SEARCH_API_KEY                   -> https://api.search.brave.com/res/v1/web/search  (web.results[].title/url/description)
    GOOGLE_CSE_KEY + GOOGLE_CSE_CX         -> https://www.googleapis.com/customsearch/v1      (items[].title/link/snippet)

Results are re-ranked toward publisher pages, repository dataset cards and download docs; blogs and
social posts are dropped. Nothing from a page is trusted beyond what it states in its own metadata.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

from .common import commercial_use, concepts_for, host_score, norm_url, slug
from .http import TIMEOUT, AdapterError, get_json

BRAVE = "https://api.search.brave.com/res/v1/web/search"
GOOGLE = "https://www.googleapis.com/customsearch/v1"


class NotConfigured(AdapterError):
    pass


def engine() -> str | None:
    if os.getenv("BRAVE_SEARCH_API_KEY"):
        return "brave"
    if os.getenv("GOOGLE_CSE_KEY") and os.getenv("GOOGLE_CSE_CX"):
        return "google"
    return None


def _raw_search(query: str, count: int) -> list[dict]:
    eng = engine()
    if eng == "brave":
        data = get_json(f"{BRAVE}?{urllib.parse.urlencode({'q': query, 'count': count, 'safesearch': 'moderate'})}",
                        headers={"X-Subscription-Token": os.environ["BRAVE_SEARCH_API_KEY"]})
        return [{"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("description", "")} for r in (data.get("web") or {}).get("results", [])]
    if eng == "google":
        data = get_json(f"{GOOGLE}?{urllib.parse.urlencode({'key': os.environ['GOOGLE_CSE_KEY'], 'cx': os.environ['GOOGLE_CSE_CX'], 'q': query, 'num': min(count, 10)})}")
        return [{"title": r.get("title", ""), "url": r.get("link", ""), "snippet": r.get("snippet", "")} for r in data.get("items", [])]
    raise NotConfigured("No web search API key. Set BRAVE_SEARCH_API_KEY (or GOOGLE_CSE_KEY and GOOGLE_CSE_CX) in backend/.env.")


def _clean(text: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", text or "")).split())


def _known_provider(url: str) -> tuple[str, str, str] | None:
    """Map repository URLs to the same ids their own adapters use, so duplicates merge."""
    p = urllib.parse.urlsplit(url)
    host = p.netloc.lower().removeprefix("www.")
    parts = [x for x in p.path.split("/") if x]
    if host == "huggingface.co" and len(parts) >= 3 and parts[0] == "datasets":
        repo = f"{parts[1]}/{parts[2]}"
        return "hf." + slug(repo.replace("/", "--")), "Hugging Face", repo
    if host == "kaggle.com" and len(parts) >= 3 and parts[0] == "datasets":
        ref = f"{parts[1]}/{parts[2]}"
        return "kaggle." + ref.lower().replace("/", "-"), "Kaggle", ref
    if host == "archive.ics.uci.edu" and len(parts) >= 2 and parts[0] == "dataset":
        return f"uci.{parts[1]}", "UCI", parts[1]
    return None


def normalize(hit: dict) -> dict | None:
    url = hit.get("url") or ""
    if not url.startswith("http") or host_score(url) < 0:
        return None
    known = _known_provider(url)
    host = urllib.parse.urlsplit(url).netloc.lower().removeprefix("www.")
    rid, provider, pid = known or ("web." + hashlib.sha1(norm_url(url).encode()).hexdigest()[:14], host, norm_url(url))
    is_doc = bool(re.search(r"\.(pdf|docx?|pptx?)$", urllib.parse.urlsplit(url).path.lower()))
    return {
        "kind": "documentation" if is_doc else "dataset",
        "id": rid,
        "title": _clean(hit.get("title"))[:200] or host,
        "description": _clean(hit.get("snippet"))[:500] or "No description in the search result.",
        "publisher": host,
        "provider": provider,
        "providerId": pid,
        "canonicalUrl": url if url.startswith("https://") else url.replace("http://", "https://", 1),
        "sourceLinks": [{"label": "Page found by web search", "url": url}],
        "tags": [],
        "formats": {"values": [], "status": "unknown"},
        "access": {"method": "unknown", "status": "unknown", "note": "Found by web search - open the page to see how to download."},
        "license": {"commercialUse": "unknown", "status": "unknown"},
        "coverage": {"temporal": {"status": "unknown"}, "spatial": {"scope": "unknown", "status": "unknown"}},
        "schemaStatus": "unknown",
        "fields": [],
        "webScore": host_score(url),
    }


def _fetch_html(url: str, limit: int = 600_000) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "dataset-starter-packs/0.3 (+dataset discovery)", "Accept": "text/html"})
    with urllib.request.urlopen(req, timeout=min(TIMEOUT, 8)) as resp:
        if "html" not in (resp.headers.get("Content-Type") or ""):
            return ""
        return resp.read(limit).decode("utf-8", errors="replace")


def _as_list(v):
    return v if isinstance(v, list) else ([] if v is None else [v])


def enrich(rec: dict) -> dict:
    """Read schema.org Dataset JSON-LD (and meta description) from the landing page. Best effort."""
    try:
        page = _fetch_html(rec["canonicalUrl"])
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return rec
    if not page:
        return rec
    meta_desc = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)', page, re.I)
    if meta_desc and rec["description"].startswith("No description"):
        rec["description"] = _clean(meta_desc.group(1))[:500]
    for block in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', page, re.S | re.I):
        try:
            data = json.loads(block.strip())
        except json.JSONDecodeError:
            continue
        for node in _as_list(data.get("@graph") if isinstance(data, dict) and "@graph" in data else data):
            if not isinstance(node, dict) or "Dataset" not in str(node.get("@type")):
                continue
            ev = rec["canonicalUrl"]
            if node.get("description"):
                rec["description"] = _clean(str(node["description"]))[:700]
            lic = node.get("license")
            lic = lic.get("name") or lic.get("url") if isinstance(lic, dict) else lic
            if lic:
                rec["license"] = {"name": str(lic)[:120], "url": str(lic) if str(lic).startswith("http") else None,
                                  "commercialUse": commercial_use(str(lic)), "status": "provider-reported", "evidence": ev}
            tc = node.get("temporalCoverage")
            if isinstance(tc, str) and re.match(r"\d{4}", tc):
                a, _, b = tc.partition("/")
                rec["coverage"]["temporal"] = {"start": a[:10] if len(a) >= 10 else f"{a[:4]}-01-01",
                                               "end": (b[:10] if len(b) >= 10 else f"{b[:4]}-12-31") if re.match(r"\d{4}", b or "") else None,
                                               "ongoing": b in ("..", ""), "granularity": [], "status": "provider-reported", "evidence": ev,
                                               "note": f"schema.org temporalCoverage: {tc}"}
            dists = _as_list(node.get("distribution"))
            fmts, files = set(), []
            for d in dists:
                if not isinstance(d, dict):
                    continue
                fmt = str(d.get("encodingFormat") or d.get("fileFormat") or "").lower()
                fmt = next((k for k in ("parquet", "csv", "json", "xlsx", "netcdf", "zip") if k in fmt), None)
                if fmt:
                    fmts.add(fmt)
                if d.get("contentUrl"):
                    files.append({"url": d["contentUrl"], "name": d.get("name") or d["contentUrl"].rsplit("/", 1)[-1], "format": fmt})
            if fmts:
                rec["formats"] = {"values": sorted(fmts), "status": "provider-reported", "evidence": ev, "exhaustive": False}
            if files:
                rec["files"] = files[:20]
                rec["access"] = {"method": "direct-download", "signInRequired": None, "status": "provider-reported", "evidence": ev}
            fields = []
            for v in _as_list(node.get("variableMeasured"))[:80]:
                name = v.get("name") if isinstance(v, dict) else str(v)
                if name:
                    concepts, solid = concepts_for(name, None)
                    fields.append({"name": name[:80], "concepts": concepts, "level": "record", "evidence": ev,
                                   "status": "provider-reported" if solid or not concepts else "unknown",
                                   "description": (v.get("description") or "")[:200] if isinstance(v, dict) else ""})
            if fields:
                rec["fields"] = fields
                rec["schemaStatus"] = "partial"
            if node.get("publisher"):
                pub = node["publisher"]
                rec["publisher"] = (pub.get("name") if isinstance(pub, dict) else str(pub))[:120] or rec["publisher"]
            break
    return rec


def search(query: str, limit: int = 10, enrich_top: int = 4) -> list[dict]:
    hits = _raw_search(f"{query} dataset download", max(limit, 10))
    recs = [r for r in (normalize(h) for h in hits) if r]
    recs.sort(key=lambda r: -r["webScore"])  # stable: keeps engine order among equal hosts
    out = []
    for i, rec in enumerate(recs[:limit]):
        rec.pop("webScore", None)
        if i < enrich_top and rec["id"].startswith("web."):
            rec = enrich(rec)
        out.append(rec)
    return out
