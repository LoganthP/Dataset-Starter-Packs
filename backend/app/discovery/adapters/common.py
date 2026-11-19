"""Helpers shared by live adapters: ids, URL normalization, field-concept detection, license mapping."""
from __future__ import annotations

import hashlib
import re
from urllib.parse import urlsplit, urlunsplit

LAT_NAMES = {"lat", "latitude", "start_lat", "end_lat", "y_lat", "lat_deg"}
LON_NAMES = {"lon", "lng", "long", "longitude", "start_lng", "start_lon", "end_lng", "x_lon", "lon_deg"}
TIME_NAMES = {"timestamp", "date", "datetime", "created_at", "created", "time", "published_at", "posted_at", "date_time",
              "created_utc", "tweet_created", "event_time", "occurred_at", "start_time"}
TIME_DTYPES = ("timestamp", "date32", "date64", "datetime", "date", "time")
NUMERIC = ("float", "double", "int", "decimal", "number")


def slug(text: str, limit: int = 100) -> str:
    s = re.sub(r"[^a-z0-9._-]+", "-", text.lower()).strip("-.")
    return s[:limit] or hashlib.sha1(text.encode()).hexdigest()[:12]


def norm_url(url: str | None) -> str:
    """Lowercase scheme/host, drop query/fragment and trailing slash - for deduplication only."""
    if not url:
        return ""
    p = urlsplit(url.strip())
    return urlunsplit((p.scheme.lower() or "https", p.netloc.lower().removeprefix("www."), p.path.rstrip("/"), "", ""))


def concepts_for(name: str, dtype: str | None) -> tuple[list[str], bool]:
    """Concepts a field supports and whether the evidence is solid (exact name or typed column)."""
    n = (name or "").strip().lower()
    t = (dtype or "").lower()
    out, solid = [], False
    if any(t.startswith(d) for d in TIME_DTYPES):
        out.append("timestamp")
        solid = True
    elif n in TIME_NAMES:
        out.append("timestamp")
        solid = True
    elif re.search(r"(date|time|_at$|timestamp)", n):
        out.append("timestamp")  # looks like a time field, but the card doesn't type it
    if n in LAT_NAMES | LON_NAMES:
        out.append("latlon")
        solid = solid or any(x in t for x in NUMERIC) or not t
    if t == "class_label" or n in ("label", "labels", "target", "class", "sentiment", "y"):
        out.append("target_label")
        solid = True
    if n in ("id", "uuid") or n.endswith("_id"):
        out.append("join_key")
        solid = True
    return out, solid


def commercial_use(license_name: str | None) -> str:
    name = (license_name or "").lower().strip()
    if not name or name in ("unknown", "other", "other (specified in description)", "none", "unspecified"):
        return "unknown"
    cc = re.search(r"creativecommons\.org/(licenses|publicdomain)/([a-z-]+)", name)
    if cc:  # license given as a Creative Commons URL
        kind = cc.group(2)
        return "not-allowed" if "nc" in kind.split("-") else "allowed"
    tokens = set(re.split(r"[^a-z0-9]+", name))
    if "nc" in tokens or "non-commercial" in name or "noncommercial" in name or "research only" in name:
        return "not-allowed"
    if any(tok in name for tok in ("cc0", "public domain", "cc-by", "cc by", "attribution 4.0", "odbl", "open database", "mit",
                                   "apache", "bsd", "open government", "pddl", "odc-by", "cdla-permissive", "openrail")):
        return "allowed"
    return "unknown"


DATA_HOSTS = {
    "huggingface.co": 3.0, "kaggle.com": 3.0, "zenodo.org": 3.0, "figshare.com": 2.5, "datadryad.org": 2.5, "dataverse": 2.5,
    "archive.ics.uci.edu": 3.0, "snap.stanford.edu": 3.0, "data.gov": 2.5, "catalog.data.gov": 3.0, "data.gov.uk": 2.5,
    "data.europa.eu": 2.5, "osf.io": 2.0, "openml.org": 2.5, "paperswithcode.com": 1.5, "registry.opendata.aws": 2.5,
    "earthdata.nasa.gov": 2.5, "icpsr.umich.edu": 2.5, "data.world": 1.5, "github.com": 1.0, "socialmediaarchive.org": 2.0,
}
NOISE_HOSTS = ("medium.com", "towardsdatascience.com", "youtube.com", "linkedin.com", "quora.com", "pinterest.", "facebook.com",
               "twitter.com", "x.com", "instagram.com", "reddit.com", "tiktok.com", "geeksforgeeks.org", "analyticsvidhya.com")


def host_score(url: str) -> float:
    host = urlsplit(url).netloc.lower().removeprefix("www.")
    if any(n in host for n in NOISE_HOSTS):
        return -5.0
    score = next((v for k, v in DATA_HOSTS.items() if k in host), 0.0)
    if host.endswith(".gov") or host.endswith(".edu") or ".gov." in host or ".ac." in host:
        score = max(score, 2.0)
    path = urlsplit(url).path.lower()
    if re.search(r"/(dataset|datasets|data)(/|$)", path):
        score += 1.0
    return score
