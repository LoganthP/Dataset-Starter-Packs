"""Read pack metadata from packs/*/pack.json - the single source of truth for the catalog."""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

from . import config

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")
REQUIRED_KEYS = {"slug", "title", "tagline", "provider", "difficulty", "skills", "question", "source", "lesson",
                 "parameters", "challenges", "entrypoints", "expected_runtime", "fixture", "last_source_check"}


class PackNotFound(KeyError):
    pass


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def pack_dir(slug: str) -> Path:
    if not SLUG_RE.match(slug):
        raise PackNotFound(slug)
    path = config.PACKS_DIR / slug
    if not (path / "pack.json").exists():
        raise PackNotFound(slug)
    return path


def load_pack(slug: str) -> dict:
    path = pack_dir(slug)
    meta = json.loads((path / "pack.json").read_text(encoding="utf-8"))
    missing = REQUIRED_KEYS - meta.keys()
    if missing:
        raise ValueError(f"{slug}/pack.json is missing keys: {sorted(missing)}")
    meta["has_preview"] = (path / "assets" / "preview.png").exists()
    return meta


def list_packs() -> list[dict]:
    packs = []
    for p in sorted(config.PACKS_DIR.glob("*/pack.json")):
        try:
            packs.append(load_pack(p.parent.name))
        except (ValueError, json.JSONDecodeError) as exc:  # a broken pack must not take down the catalog
            packs.append({"slug": p.parent.name, "title": p.parent.name, "error": str(exc)})
    return packs


def pack_documents(slug: str) -> dict:
    path = pack_dir(slug)
    return {
        "readme": _read(path / "README.md"),
        "data_dictionary": _read(path / "data-dictionary.md"),
    }


def data_status(slug: str) -> dict:
    """What real data is cached locally for this pack."""
    raw = pack_dir(slug) / "data" / "raw"
    files = []
    if raw.exists():
        for f in sorted(raw.iterdir()):
            if f.is_file() and not f.name.endswith(".source.json") and f.name != "source.json":
                files.append({"name": f.name, "bytes": f.stat().st_size,
                              "modified": dt.datetime.fromtimestamp(f.stat().st_mtime, dt.UTC).isoformat(timespec="seconds")})
    provenance = []
    if raw.exists():
        for meta in sorted(raw.glob("*source.json")):
            try:
                provenance.append(json.loads(meta.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                pass
    expected = load_pack(slug)["source"].get("files", [])
    return {"cached_files": files, "provenance": provenance, "expected_files": expected, "has_real_data": bool(files)}


def validate_params(meta: dict, mode: str, params: dict) -> dict:
    """Validate run parameters against the pack's declared schema. Unknown keys are rejected."""
    if mode not in ("sample", "real"):
        raise ValueError("mode must be 'sample' or 'real'")
    spec = {p["name"]: p for p in meta.get("parameters", [])}
    clean: dict[str, str] = {}
    for key, value in (params or {}).items():
        if key not in spec:
            raise ValueError(f"Unknown parameter {key!r}. Allowed: {', '.join(spec) or 'none'}")
        p = spec[key]
        if "modes" in p and mode not in p["modes"]:
            continue
        if value in (None, ""):
            continue
        kind = p.get("type", "text")
        if kind == "number":
            try:
                num = float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{p['label']} must be a number") from exc
            if "min" in p and num < p["min"] or "max" in p and num > p["max"]:
                raise ValueError(f"{p['label']} must be between {p.get('min')} and {p.get('max')}")
            clean[key] = str(num)
        elif kind == "select":
            if str(value) not in p["options"]:
                raise ValueError(f"{p['label']} must be one of {', '.join(p['options'])}")
            clean[key] = str(value)
        elif kind == "date":
            try:
                dt.date.fromisoformat(str(value))
            except ValueError as exc:
                raise ValueError(f"{p['label']} must be a date (YYYY-MM-DD)") from exc
            clean[key] = str(value)
        else:
            text = str(value)
            if len(text) > 200 or "\n" in text:
                raise ValueError(f"{p['label']} is too long")
            clean[key] = text
    if {"start", "end"} <= clean.keys() and clean["start"] > clean["end"]:
        raise ValueError("Start date must be before end date")
    return clean
