"""Loader template. Keep it self-contained: standard library + pandas only.

Contract (the web app and CI rely on it):
* load(mode) returns validated data for mode "sample" (fixture) or "real" (official source).
* Real mode downloads with a timeout, caches in data/raw/, writes data/raw/source.json.
* Errors raise DataError with a one-line recovery hint.
"""
from __future__ import annotations

import datetime as dt
import json
import urllib.error
import urllib.request
from pathlib import Path

import pandas as pd

PACK_DIR = Path(__file__).resolve().parent
RAW_DIR = PACK_DIR / "data" / "raw"
RAW_FILE = RAW_DIR / "data.csv"
FIXTURE_FILE = PACK_DIR / "fixtures" / "sample.csv"
SOURCE_URL = "https://example.org/data.csv"  # TODO
EXPECTED_COLUMNS = ["id", "feature", "target"]  # TODO


class DataError(RuntimeError):
    pass


def fetch(force: bool = False) -> Path:
    if RAW_FILE.exists() and not force:
        return RAW_FILE
    try:
        with urllib.request.urlopen(SOURCE_URL, timeout=60) as r:
            payload = r.read()
    except (urllib.error.URLError, TimeoutError) as exc:
        raise DataError(f"Could not download {SOURCE_URL} ({exc}). Place the file at {RAW_FILE} manually.") from exc
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    RAW_FILE.write_bytes(payload)
    (RAW_DIR / "source.json").write_text(json.dumps({
        "source_url": SOURCE_URL,
        "retrieved_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
    }, indent=2))
    return RAW_FILE


def validate(df: pd.DataFrame) -> pd.DataFrame:
    missing = [c for c in EXPECTED_COLUMNS if c not in df.columns]
    if missing:
        raise DataError(f"Required column(s) missing: {', '.join(missing)}")
    return df


def load(mode: str = "sample") -> pd.DataFrame:
    if mode == "sample":
        return validate(pd.read_csv(FIXTURE_FILE))
    if mode == "real":
        return validate(pd.read_csv(fetch()))
    raise DataError(f"Unknown mode {mode!r}")


def provenance(mode: str) -> dict:
    if mode == "sample":
        return {"kind": "synthetic fixture"}
    meta = RAW_DIR / "source.json"
    return json.loads(meta.read_text()) if meta.exists() else {"kind": "real"}
