"""Resolve a dataset's downloadable files from its provider, on demand (the "Analyze dataset" action).

Search results often say "Format unknown": DataCite, web search and Kaggle listings don't include file lists.
This module asks the provider itself, in this order, and stops at the first that answers:

  Hugging Face  datasets-server /parquet                         (Parquet conversions of every split)
  Zenodo        GET zenodo.org/api/records/<id>                    files[].key/size/links.self
  Figshare      GET api.figshare.com/v2/articles/<id>/files        name/size/download_url
  Dryad         GET datadryad.org/api/v2/datasets/<doi> -> version -> files
  Dataverse     GET <host>/api/datasets/:persistentId?persistentId=doi:..   latestVersion.files[].dataFile
  Socrata       GET <host>/api/views/<4x4>.json  -> <host>/api/views/<4x4>/rows.csv?accessType=DOWNLOAD
  CKAN          GET <host>/api/3/action/package_show?id=<name>    resources[]
  Kaggle        GET kaggle.com/api/v1/datasets/list/<owner>/<slug> (needs KAGGLE_USERNAME/KAGGLE_KEY; otherwise sign-in)
  UCI           archive.ics.uci.edu/static/public/<id>/data.csv
  Any page      schema.org Dataset JSON-LD distribution[].contentUrl, then links ending in .csv/.parquet/...

Only URLs returned here can be analyzed (analysis.py checks), so the API never fetches arbitrary URLs.
"""
from __future__ import annotations

import html
import json
import os
import re
import time
import urllib.parse

from .adapters import huggingface
from .adapters import kaggle as kaggle_ad
from .adapters.http import AdapterError, get_json, get_text

ANALYZABLE = ("csv", "tsv", "parquet", "json", "zip", "xlsx", "sinex", "sinex-gz", "sinex-z", "xls", "ods", "stata", "sas", "spss", "netcdf",
              "hdf5", "tar", "gz", "bz2", "xz", "7z", "xml")
_EXT = ((".snx.gz", "sinex-gz"), (".sinex.gz", "sinex-gz"), (".snx.z", "sinex-z"), (".snx", "sinex"), (".sinex", "sinex"), (".parquet", "parquet"), (".csv.gz", "csv"), (".csv.zip", "zip"), (".csv", "csv"), (".tsv", "tsv"), (".tab", "tsv"), (".jsonl", "json"),
        (".ndjson", "json"), (".geojson", "json"), (".json", "json"), (".zip", "zip"), (".xlsx", "xlsx"), (".xlsm", "xlsx"), (".xls", "xls"), (".ods", "ods"), (".dta", "stata"),
        (".sas7bdat", "sas"), (".xpt", "sas"), (".sav", "spss"), (".tar.gz", "tar"), (".tgz", "tar"), (".tar.bz2", "tar"), (".tar.xz", "tar"),
        (".tar", "tar"), (".txt", "txt"), (".xml", "xml"), (".pdf", "pdf"), (".nc", "netcdf"), (".nc4", "netcdf"), (".h5", "hdf5"),
        (".hdf5", "hdf5"), (".he5", "hdf5"), (".shp", "shp"), (".gz", "gz"), (".bz2", "bz2"), (".xz", "xz"), (".7z", "7z"), (".rar", "rar"),
        (".docx", "docx"))
_MIME = {"text/csv": "csv", "application/csv": "csv", "application/vnd.apache.parquet": "parquet", "application/x-parquet": "parquet",
         "application/json": "json", "application/zip": "zip", "text/tab-separated-values": "tsv", "application/pdf": "pdf",
         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx"}
_CACHE: dict[str, tuple[float, dict]] = {}
TTL = 900
MAX_FILES = 80


def fmt_of(name: str | None, hint: str | None = None) -> str | None:
    if hint:
        h = hint.lower().strip().lstrip(".")
        if h in _MIME:
            return _MIME[h]
        if h in ("csv", "tsv", "parquet", "json", "jsonl", "geojson", "zip", "xlsx", "xls", "pdf", "txt", "sinex", "snx"):
            return {"jsonl": "json", "geojson": "json", "snx": "sinex"}.get(h, h)
    n = (name or "").lower().split("?")[0].split("#")[0]
    if n.endswith("/content"):  # Zenodo: .../files/<key>/content
        n = n[: -len("/content")]
    if "rows.csv" in n:
        return "csv"
    for ext, fmt in _EXT:
        if n.endswith(ext):
            return fmt
    return None


def _file(url: str, name: str | None = None, size=None, fmt_hint: str | None = None, **extra) -> dict:
    name = name or urllib.parse.unquote(url.split("?")[0].rstrip("/").rsplit("/", 1)[-1]) or url
    fmt = fmt_of(name, fmt_hint) or fmt_of(url)
    try:
        size = int(size) if size not in (None, "") else None
    except (TypeError, ValueError):
        size = None
    return {"url": url, "name": name, "format": fmt or "unknown", "bytes": size, "supported": fmt in ANALYZABLE, **extra}


def _host(url: str) -> str:
    return urllib.parse.urlparse(url or "").netloc.lower()


def _urls(rec: dict) -> list[str]:
    out = [rec.get("canonicalUrl") or ""] + [s.get("url", "") for s in rec.get("sourceLinks", [])]
    if rec.get("doi"):
        out.append(f"https://doi.org/{rec['doi']}")
    return [u for u in dict.fromkeys(out) if u.startswith("http")]


# ---------------------------------------------------------------- providers
def _zenodo(rec: dict, urls: list[str]) -> dict | None:
    rid = None
    for u in urls + [rec.get("doi") or ""]:
        m = re.search(r"zenodo\.org/(?:records?|deposit|doi/10\.5281/zenodo\.)/?(\d+)", u) or re.search(r"10\.5281/zenodo\.(\d+)", u, re.I)
        if m:
            rid = m.group(1)
            break
    if not rid:
        return None
    data = get_json(f"https://zenodo.org/api/records/{rid}")
    files = data.get("files") or []
    if isinstance(files, dict):  # InvenioRDM /files endpoint shape
        files = files.get("entries") or []
    out = [_file((f.get("links") or {}).get("self") or (f.get("links") or {}).get("content") or f"https://zenodo.org/records/{rid}/files/{f['key']}?download=1",
                 f.get("key") or f.get("filename"), f.get("size") or f.get("filesize")) for f in files]
    restricted = ((data.get("access") or {}).get("files") == "restricted") or (data.get("metadata", {}).get("access_right") == "restricted")
    return {"files": out, "via": "Zenodo API", "signInRequired": restricted and not out,
            "note": "Zenodo lists the files but they are restricted to approved users." if restricted and not out else None}


def _figshare(rec: dict, urls: list[str]) -> dict | None:
    aid = None
    for u in urls + [rec.get("doi") or ""]:
        m = re.search(r"10\.6084/m9\.figshare\.(\d+)", u, re.I) or re.search(r"figshare\.com/(?:articles/[^/]+/[^/]+|s)/(\d+)", u)
        if m:
            aid = m.group(1)
            break
    if not aid:
        return None
    files = get_json(f"https://api.figshare.com/v2/articles/{aid}/files")
    return {"files": [_file(f["download_url"], f.get("name"), f.get("size")) for f in files if f.get("download_url")], "via": "Figshare API"}


def _dryad(rec: dict, urls: list[str]) -> dict | None:
    doi = None
    for u in urls + [rec.get("doi") or ""]:
        m = re.search(r"(10\.5061/dryad\.[a-z0-9]+)", u, re.I)
        if m:
            doi = m.group(1)
            break
    if not doi:
        return None
    ds = get_json(f"https://datadryad.org/api/v2/datasets/{urllib.parse.quote('doi:' + doi, safe='')}")
    href = ((ds.get("_links") or {}).get("stash:version") or {}).get("href")
    if not href:
        return {"files": [], "via": "Dryad API"}
    data = get_json(f"https://datadryad.org{href}/files")
    files = (data.get("_embedded") or {}).get("stash:files") or []
    return {"files": [_file("https://datadryad.org" + f["_links"]["stash:download"]["href"], f.get("path"), f.get("size"), f.get("mimeType"))
                      for f in files if (f.get("_links") or {}).get("stash:download")], "via": "Dryad API"}


def _dataverse(rec: dict, urls: list[str]) -> dict | None:
    for u in urls:
        m = re.search(r"persistentId=(doi:[^&#]+)", u)
        if m and "dataset.xhtml" in u:
            base = f"https://{_host(u)}"
            pid = urllib.parse.unquote(m.group(1))
            data = get_json(f"{base}/api/datasets/:persistentId/?persistentId={urllib.parse.quote(pid, safe=':/')}")
            files = (((data.get("data") or {}).get("latestVersion") or {}).get("files")) or []
            out = []
            for f in files:
                df = f.get("dataFile") or {}
                name = df.get("originalFileName") or df.get("filename")
                hint = df.get("originalFileFormat") or df.get("contentType")
                fmt_url = "?format=original" if df.get("originalFileName") else ""
                if f.get("restricted"):
                    continue
                out.append(_file(f"{base}/api/access/datafile/{df['id']}{fmt_url}", name, df.get("originalFileSize") or df.get("filesize"), hint))
            return {"files": out, "via": "Dataverse API"}
    return None


def _socrata(rec: dict, urls: list[str]) -> dict | None:
    for u in urls:
        p = urllib.parse.urlparse(u)
        ids = [s for s in p.path.split("/") if re.fullmatch(r"[a-z0-9]{4}-[a-z0-9]{4}", s)]
        if not ids or not p.netloc:
            continue
        base = f"https://{p.netloc}"
        meta = get_json(f"{base}/api/views/{ids[-1]}.json")
        if not isinstance(meta, dict) or "id" not in meta:
            continue
        name = re.sub(r"[^A-Za-z0-9]+", "_", meta.get("name") or ids[-1]).strip("_")[:80] + ".csv"
        rid = ids[-1]
        date_fields = [c["fieldName"] for c in meta.get("columns", []) if c.get("dataTypeName") in ("calendar_date", "floating_timestamp", "date")
                       and c.get("fieldName") and not c["fieldName"].startswith(":")]
        # The bulk export streams the whole table (Chicago crashes: 1M+ rows, no Content-Length). Analyze uses the
        # SODA endpoint for samples instead: a row limit with a stable order, plus a count(*) for the true total.
        return {"files": [_file(f"{base}/api/views/{rid}/rows.csv?accessType=DOWNLOAD", name, None, "csv",
                                sample_url=f"{base}/resource/{rid}.csv?$limit={{n}}&$order=:id",
                                count_url=f"{base}/resource/{rid}.json?$select=count(*)",
                                sample_method="first {n} rows ordered by row id (:id) from the Socrata API",
                                resource_url=f"{base}/resource/{rid}.csv", date_fields=date_fields)],
                "via": "Socrata API"}
    return None


def _ckan(rec: dict, urls: list[str]) -> dict | None:
    for u in urls:
        p = urllib.parse.urlparse(u)
        m = re.search(r"/dataset/(?:[^/]+/)?([A-Za-z0-9_.-]+)/?$", p.path)
        if not m or "zenodo" in p.netloc or "kaggle" in p.netloc:
            continue
        try:
            data = get_json(f"https://{p.netloc}/api/3/action/package_show?id={urllib.parse.quote(m.group(1))}")
        except AdapterError:
            continue
        res = ((data or {}).get("result") or {}).get("resources") or []
        if not (data or {}).get("success") and not res:
            continue
        return {"files": [_file(r["url"], r.get("name") if fmt_of(r.get("name")) else (r.get("name") or "") + (f".{r['format'].lower()}" if r.get("format") else ""),
                                r.get("size"), r.get("format") or r.get("mimetype")) for r in res if (r.get("url") or "").startswith("http")],
                "via": "CKAN API"}
    return None


def _kaggle(rec: dict, urls: list[str], user: str | None = None) -> dict | None:
    ref = None
    for u in urls:
        m = re.search(r"kaggle\.com/datasets/([^/?#]+/[^/?#]+)", u)
        if m:
            ref = m.group(1)
            break
    if not ref:
        return None
    from .. import kaggle_connect

    if user and kaggle_connect.auth_headers(user):
        try:
            files = kaggle_connect.list_files(user, ref)
        except kaggle_connect.ConnectError as exc:
            if exc.kind == "network":
                raise AdapterError(str(exc)) from exc
            return {"files": [], "via": "Kaggle API (your account)", "signInRequired": True, "connect": "kaggle", "consentUrl": kaggle_connect.consent_url(ref),
                    "note": f"{exc} If the dataset asks you to accept its terms, accept them on Kaggle and refresh."}
        listed = [_file(kaggle_connect.download_url(ref, f["name"]), f["name"], f.get("totalBytes"), auth="kaggle") for f in files if f.get("name")]
        whole = _file(kaggle_connect.download_url(ref, None), f"{ref.split('/', 1)[1]}.zip", sum(f.get("totalBytes") or 0 for f in files) or None,
                      "zip", auth="kaggle", label="Entire dataset (ZIP from Kaggle)", group="whole")
        return {"files": ([whole] if len(listed) != 1 else []) + listed, "via": "Kaggle API (your account)", "connect": "kaggle"}
    auth = kaggle_ad._auth_header()
    if not auth:
        return {"files": [], "via": "Kaggle", "signInRequired": True, "connect": "kaggle",
                "note": "Connect your Kaggle account to list and fetch this dataset's files here, or download a file from Kaggle and upload it."}
    owner, slug = ref.split("/", 1)
    data = get_json(f"{kaggle_connect.base()}/api/v1/datasets/list/{owner}/{slug}", headers=auth)
    files = data.get("datasetFiles") or data.get("files") or []
    return {"files": [_file(kaggle_connect.download_url(ref, f["name"]), f["name"], f.get("totalBytes"), auth="kaggle") for f in files if f.get("name")],
            "via": "Kaggle API (server credentials)", "connect": "kaggle"}


def _uci(rec: dict, urls: list[str]) -> dict | None:
    if rec.get("provider") == "UCI" and str(rec.get("providerId", "")).isdigit():
        return {"files": [_file(f"https://archive.ics.uci.edu/static/public/{rec['providerId']}/data.csv", "data.csv", None, "csv")], "via": "UCI"}
    return None


def _hf_pair_prefix(path: str) -> tuple[str, str] | None:
    """('state_vectors'|'metadata', '<timestamp>_<pid>') for FraDra-style paired Parquet files."""
    m = re.match(r"^(?:.*/)?(state_vectors|metadata)/(.+?)_(state_vectors|metadata)\.parquet$", path)
    if m and m.group(1) == m.group(3):
        return m.group(1), m.group(2)
    return None


def _huggingface(rec: dict, urls: list[str]) -> dict | None:
    repo = rec.get("providerId") if rec.get("previewProvider") == "huggingface" else None
    if not repo:
        for u in urls:
            m = re.search(r"huggingface\.co/datasets/([^/?#]+/[^/?#]+)", u)
            if m:
                repo = m.group(1)
                break
    if not repo:
        return None
    errors, files, via = [], [], []
    try:  # the repository itself, every folder, every page
        listing = huggingface.tree(repo)
        raw = [f for f in listing["files"] if not re.search(r"(^|/)\.|README|\.gitattributes$", f["path"])]
        sv, md, rest = {}, {}, []
        for f in raw:
            pp = _hf_pair_prefix(f["path"])
            if pp and pp[0] == "state_vectors":
                sv[pp[1]] = f
            elif pp:
                md[pp[1]] = f
            else:
                rest.append(f)
        for prefix in sorted(sv, reverse=True):
            a = sv[prefix]
            b = md.get(prefix)
            entry = _file(huggingface.resolve_url(repo, a["path"]), a["path"], a["size"], "parquet", group="pairs", prefix=prefix)
            if b:
                entry.update({"pair_url": huggingface.resolve_url(repo, b["path"]), "pair_name": b["path"], "pair_bytes": b["size"],
                              "label": f"{prefix}: state vectors + metadata"})
            files.append(entry)
        files += [_file(huggingface.resolve_url(repo, md[p]["path"]), md[p]["path"], md[p]["size"], "parquet", group="unpaired", prefix=p)
                  for p in sorted(set(md) - set(sv), reverse=True)]
        files += [_file(huggingface.resolve_url(repo, f["path"]), f["path"], f["size"]) for f in rest]
        via.append(f"Hugging Face repository ({len(raw):,} files in {listing['pages']} page{'s' if listing['pages'] != 1 else ''}"
                   f"{', listing truncated' if listing['truncated'] else ''})")
        pairs = sum(1 for f in files if f.get("pair_url"))
    except AdapterError as exc:
        errors.append(f"tree: {exc}")
        pairs = 0
    try:  # plus the datasets-server Parquet conversion, when it exists
        conv = [{**f, "supported": True, "group": "converted"} for f in huggingface.files(repo)]
        if conv:
            files += conv
            via.append("datasets-server Parquet conversion")
    except AdapterError as exc:
        errors.append(f"datasets-server: {exc}")
    if not files and errors:
        raise AdapterError("; ".join(errors))
    note = (f"{pairs:,} state-vector files are paired with their metadata by the shared <timestamp>_<pid> prefix. "
            "Choose a pair to analyze both together.") if pairs else None
    return {"files": files, "via": " + ".join(via) or "Hugging Face", "note": note, "errors": errors}


def _landing_page(rec: dict, urls: list[str]) -> dict | None:
    """Last resort: read the landing page for schema.org distributions and direct file links."""
    for u in urls[:2]:
        try:
            final, page = get_text(u)
        except AdapterError:
            continue
        found: dict[str, dict] = {}
        for block in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', page, re.S | re.I):
            try:
                data = json.loads(html.unescape(block.strip()))
            except json.JSONDecodeError:
                continue
            for node in data if isinstance(data, list) else data.get("@graph", [data]) if isinstance(data, dict) else []:
                dist = node.get("distribution") if isinstance(node, dict) else None
                for d in dist if isinstance(dist, list) else [dist] if isinstance(dist, dict) else []:
                    url = d.get("contentUrl") or d.get("url")
                    if isinstance(url, str) and url.startswith("http"):
                        found.setdefault(url, _file(url, d.get("name"), d.get("contentSize") if str(d.get("contentSize", "")).isdigit() else None,
                                                    d.get("encodingFormat") or d.get("fileFormat")))
        for href in re.findall(r'href="([^"]+)"', page):
            url = urllib.parse.urljoin(final, html.unescape(href))
            if url.startswith("http") and fmt_of(url) in ANALYZABLE and url not in found:
                found[url] = _file(url)
        if found:
            return {"files": list(found.values()), "via": f"links on {_host(final)}"}
        # A DOI that redirected somewhere we know (e.g. doi.org -> zenodo.org) gets a second chance.
        if final != u:
            for fn in (_zenodo, _figshare, _dryad, _dataverse, _socrata, _ckan):
                try:
                    res = fn(rec, [final])
                except AdapterError:
                    res = None
                if res is not None:
                    return res
    return None


RESOLVERS = (_huggingface, _zenodo, _figshare, _dryad, _dataverse, _kaggle, _socrata, _uci, _ckan, _landing_page)


def _cache_key(rec: dict, user: str | None) -> str:
    kaggle = "kaggle.com" in (rec.get("canonicalUrl") or "") or rec.get("provider") == "Kaggle"
    return f"{rec['id']}|{user}" if kaggle and user else rec["id"]


def resolve(rec: dict, refresh: bool = False, user: str | None = None) -> dict:
    """{files:[{url,name,format,bytes,supported,...}], total, via, signInRequired, note, errors}. Cached for 15 minutes.
    `files` holds every listed file (Hugging Face repos can list thousands); the API pages through them."""
    key = _cache_key(rec, user)
    hit = _CACHE.get(key)
    if hit and not refresh and time.time() - hit[0] < TTL:
        return hit[1]
    urls = _urls(rec)
    errors: list[str] = []
    result = empty = None
    for fn in RESOLVERS:
        try:
            got = fn(rec, urls, user) if fn is _kaggle else fn(rec, urls)
        except AdapterError as exc:
            errors.append(f"{fn.__name__.strip('_')}: {exc}")
            continue
        if got is None:
            continue
        errors += got.get("errors") or []
        if got["files"] or got.get("signInRequired"):
            result = got
            break
        empty = empty or got  # e.g. a record with no public files: keep its note, still try the landing page
    result = result or empty
    listed = [_file(f["url"], f.get("name"), f.get("bytes"), f.get("format")) for f in rec.get("files", []) if (f.get("url") or "").startswith("http")]
    result = result or {"files": [], "via": None}
    seen = {f["url"] for f in result["files"]}
    files = result["files"] + [f for f in listed if f["url"] not in seen]
    local_ok = os.getenv("DSP_ALLOW_LOCAL_SOURCES") == "1"  # tests and the offline demo only; never in production
    files = [f for f in files if f["url"].startswith("https://") or f.get("auth") or (local_ok and f["url"].startswith(("http://127.0.0.1", "http://localhost")))]
    order = {"whole": -1, "pairs": 0, "unpaired": 2, "converted": 3}
    files.sort(key=lambda f: (not f["supported"], order.get(f.get("group"), 1), f["format"] not in ("parquet", "csv", "zip")))
    out = {"files": files, "total": len(files), "via": result.get("via"), "signInRequired": bool(result.get("signInRequired")),
           "note": result.get("note"), "errors": errors, "connect": result.get("connect"), "consentUrl": result.get("consentUrl"),
           "pairs": sum(1 for f in files if f.get("pair_url"))}
    _CACHE[key] = (time.time(), out)
    return out


def page(res: dict, offset: int = 0, limit: int = MAX_FILES, q: str | None = None) -> dict:
    files = res["files"]
    if q:
        ql = q.lower()
        files = [f for f in files if ql in (f.get("name") or "").lower() or ql in (f.get("pair_name") or "").lower()]
    return {**res, "files": files[offset: offset + limit], "total": len(res["files"]), "matched": len(files), "offset": offset, "limit": limit}


def find(rec: dict, url: str, user: str | None = None) -> dict | None:
    """The resolved file with this URL (or the metadata half of a pair), re-resolving once if the cache expired."""
    for refresh in (False, True):
        for f in resolve(rec, refresh=refresh, user=user)["files"]:
            if f["url"] == url:
                return f
            if f.get("pair_url") == url:
                return {"url": f["pair_url"], "name": f["pair_name"], "format": "parquet", "bytes": f.get("pair_bytes"), "supported": True}
    return None
