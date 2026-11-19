"""Hugging Face Hub dataset search (public; optional HF_TOKEN for higher rate limits).

    search:  https://huggingface.co/api/datasets?search=<q>&limit=<n>&full=true
             -> [{id, author, description, tags, cardData{license, task_categories, pretty_name, dataset_info{features,...}}, gated, lastModified, ...}]
    preview: https://datasets-server.huggingface.co/first-rows?dataset=<id>&config=<c>&split=<s>
    files:   https://datasets-server.huggingface.co/parquet?dataset=<id>

The card's dataset_info lists each config's features, so the schema is "complete" when every
config documents its features. Dates are rarely documented on cards and stay unknown.
"""
from __future__ import annotations

import os
import urllib.parse

from .common import commercial_use, concepts_for, slug
from .http import AdapterError, get_json, get_json_with_headers

SEARCH_URL = "https://huggingface.co/api/datasets"
SERVER = "https://datasets-server.huggingface.co"
HUB = os.getenv("HF_HUB_BASE", "https://huggingface.co").rstrip("/")
TREE_MAX_PAGES = int(os.getenv("DSP_HF_TREE_MAX_PAGES", "100"))  # 1,000 entries per page
TASK_PURPOSE = {"text-classification": "classification", "token-classification": "classification", "image-classification": "classification",
                "tabular-classification": "classification", "tabular-regression": "regression", "time-series-forecasting": "forecasting",
                "summarization": "exploratory", "question-answering": "exploratory", "feature-extraction": "exploratory"}
MODALITY = {"text": "text", "tabular": "tabular", "image": "image", "timeseries": "time-series", "geospatial": "geospatial", "audio": "audio"}


def _headers() -> dict:
    token = os.getenv("HF_TOKEN")
    return {"Authorization": f"Bearer {token}"} if token else {}


def record_id(repo_id: str) -> str:
    return "hf." + slug(repo_id.replace("/", "--"))


def _dtype(d) -> str:
    if isinstance(d, str):
        return d
    if isinstance(d, dict):
        if "class_label" in d:
            return "class_label"
        return "struct"
    if isinstance(d, list):
        return "list"
    return "unknown"


def _infos(card: dict) -> list[dict]:
    info = card.get("dataset_info")
    if isinstance(info, dict):
        return [{**info, "config_name": info.get("config_name", "default")}]
    return [i for i in info or [] if isinstance(i, dict)]


def normalize(item: dict) -> dict:
    repo = item["id"]
    url = f"https://huggingface.co/datasets/{repo}"
    card = item.get("cardData") or {}
    tags = [t for t in item.get("tags") or [] if isinstance(t, str)]
    infos = _infos(card)

    fields_by_name: dict[str, dict] = {}
    rows = 0
    for info in infos:
        cfg = info.get("config_name", "default")
        for feat in info.get("features") or []:
            name = feat.get("name")
            if not name:
                continue
            dtype = _dtype(feat.get("dtype")) if "dtype" in feat else ("class_label" if "class_label" in feat else _dtype(feat.get("_type")))
            concepts, solid = concepts_for(name, dtype)
            f = fields_by_name.setdefault(name, {
                "name": name, "type": dtype, "concepts": concepts, "level": "record", "configs": [],
                "status": "provider-reported" if solid or not concepts else "unknown", "evidence": url,
                "description": "Class label" if dtype == "class_label" else "",
            })
            if cfg not in f["configs"]:
                f["configs"].append(cfg)
        for split in info.get("splits") or []:
            rows += int(split.get("num_examples") or 0)
    configs = [i.get("config_name", "default") for i in infos]
    schema = "complete" if infos and all(i.get("features") for i in infos) else ("partial" if fields_by_name else "unknown")
    for f in fields_by_name.values():
        if len(configs) > 1:
            f["description"] = (f["description"] + ". " if f["description"] else "") + f"In {len(f['configs'])} of {len(configs)} configs."

    lic = card.get("license")
    lic = ", ".join(lic) if isinstance(lic, list) else lic
    tasks = card.get("task_categories") or []
    formats = sorted({t.split(":", 1)[1] for t in tags if t.startswith("format:")})
    modalities = sorted({MODALITY[t.split(":", 1)[1]] for t in tags if t.startswith("modality:") and t.split(":", 1)[1] in MODALITY})
    description = (item.get("description") or "").strip()
    if not description or description.lower().startswith("more information needed"):
        description = f"Hugging Face dataset {repo}." + (f" Tasks: {', '.join(tasks)}." if tasks else "")
    gated = item.get("gated") not in (False, None, "false")
    download = sum(int(i.get("download_size") or 0) for i in infos) or None
    return {
        "id": record_id(repo),
        "title": card.get("pretty_name") or repo.split("/")[-1].replace("_", " ").replace("-", " ").title(),
        "description": " ".join(description.split())[:700],
        "publisher": f"{item.get('author') or repo.split('/')[0]} (via Hugging Face)",
        "provider": "Hugging Face",
        "providerId": repo,
        "canonicalUrl": url,
        "sourceLinks": [{"label": "Hugging Face dataset card", "url": url}],
        "tags": sorted({t.split(":", 1)[1].replace("-", " ") for t in tags if t.startswith(("task_categories:", "task_ids:", "language:"))})[:15],
        "purposes": sorted({TASK_PURPOSE[t] for t in tasks if t in TASK_PURPOSE}),
        "characteristics": modalities,
        "formats": {"values": formats, "status": "provider-reported" if formats else "unknown", "evidence": url, "exhaustive": False,
                    "note": "Most Hub datasets can also be exported as Parquet by the datasets-server."},
        "access": {"method": "sign-in" if gated else "direct-download", "signInRequired": gated, "status": "provider-reported", "evidence": url,
                   "note": "Gated: accept the terms on the dataset page while signed in." if gated else None},
        "license": {"name": lic or None, "url": url, "commercialUse": commercial_use(lic), "status": "provider-reported" if lic and lic != "unknown" else "unknown",
                    "evidence": url, "note": "The dataset card lists the license as unknown." if lic == "unknown" else None},
        "coverage": {"temporal": {"status": "unknown", "note": "Hugging Face cards rarely document observation dates."},
                     "spatial": {"scope": "unknown", "status": "unknown"}},
        "schemaStatus": schema,
        "fields": list(fields_by_name.values()),
        "configs": configs,
        "size": {"rows": rows or None, "bytes": download},
        "sourceUpdatedAt": (item.get("lastModified") or "")[:10] or None,
        "previewProvider": "huggingface",
    }


def search(query: str, limit: int = 12) -> list[dict]:
    url = f"{SEARCH_URL}?{urllib.parse.urlencode({'search': query, 'limit': limit, 'full': 'true', 'sort': 'downloads', 'direction': -1})}"
    data = get_json(url, headers=_headers())
    return [normalize(i) for i in data if isinstance(i, dict) and i.get("id") and not i.get("private") and not i.get("disabled")]


def preview(repo: str, config: str | None = None) -> dict:
    splits = get_json(f"{SERVER}/splits?{urllib.parse.urlencode({'dataset': repo})}", headers=_headers()).get("splits", [])
    if not splits:
        raise ValueError("The datasets-server has no splits for this dataset (it may be gated or not converted).")
    pick = next((s for s in splits if config and s["config"] == config), splits[0])
    rows = get_json(f"{SERVER}/first-rows?{urllib.parse.urlencode({'dataset': repo, 'config': pick['config'], 'split': pick['split']})}", headers=_headers())
    cols = [f["name"] for f in rows.get("features", [])]
    types = {f["name"]: (f.get("type") or {}).get("dtype") or (f.get("type") or {}).get("_type") for f in rows.get("features", [])}
    return {"config": pick["config"], "split": pick["split"], "configs": sorted({s["config"] for s in splits}),
            "columns": [{"name": c, "type": types.get(c)} for c in cols],
            "rows": [[r["row"].get(c) for c in cols] for r in rows.get("rows", [])[:20]],
            "source": f"{SERVER}/first-rows?dataset={repo}&config={pick['config']}&split={pick['split']}"}


def files(repo: str) -> list[dict]:
    data = get_json(f"{SERVER}/parquet?{urllib.parse.urlencode({'dataset': repo})}", headers=_headers())
    return [{"url": f["url"], "name": f"{f['config']}/{f['split']}/{f['filename']}", "format": "parquet", "bytes": f.get("size"),
             "config": f.get("config"), "split": f.get("split")} for f in data.get("parquet_files", [])]


def _next_link(headers: dict) -> str | None:
    link = headers.get("Link") or headers.get("link") or ""
    for part in link.split(","):
        if 'rel="next"' in part:
            return part[part.find("<") + 1: part.find(">")]
    return None


def tree(repo: str, revision: str = "main") -> dict:
    """Every file in the dataset repo, recursively, following the API's cursor pagination (Link: rel="next").
    {files:[{path,size}], pages, truncated}."""
    url = f"{HUB}/api/datasets/{repo}/tree/{urllib.parse.quote(revision)}?recursive=true&expand=false"
    files, pages = [], 0
    while url and pages < TREE_MAX_PAGES:
        data, headers = get_json_with_headers(url, headers=_headers())
        if not isinstance(data, list):
            raise AdapterError("Unexpected tree listing")
        files += [{"path": e["path"], "size": e.get("size") or (e.get("lfs") or {}).get("size")} for e in data if e.get("type") == "file"]
        pages += 1
        nxt = _next_link(headers)
        url = urllib.parse.urljoin(HUB, nxt) if nxt else None
    return {"files": files, "pages": pages, "truncated": bool(url)}


def resolve_url(repo: str, path: str, revision: str = "main") -> str:
    return f"{HUB}/datasets/{repo}/resolve/{urllib.parse.quote(revision)}/{urllib.parse.quote(path)}"
