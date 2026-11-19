"""Data loader for the UCI Dry Bean pack.

* ``sample`` reads a synthetic table with the same 16 shape features and 7 classes.
* ``real`` downloads the official UCI ZIP, reads ``Dry_Bean_Dataset.xlsx`` (needs openpyxl),
  caches it as ``data/raw/dry_bean.csv`` and records provenance in ``source.json``.

    python load_data.py --fetch
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import io
import json
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import pandas as pd

PACK_DIR = Path(__file__).resolve().parent
RAW_DIR = PACK_DIR / "data" / "raw"
RAW_FILE = RAW_DIR / "dry_bean.csv"
SOURCE_META = RAW_DIR / "source.json"
FIXTURE_FILE = PACK_DIR / "fixtures" / "dry_bean_sample.csv"

SOURCE_URL = "https://archive.ics.uci.edu/static/public/602/dry+bean+dataset.zip"
DATASET_PAGE = "https://archive.ics.uci.edu/dataset/602/dry+bean+dataset"
CITATION = "Dry Bean [Dataset]. (2020). UCI Machine Learning Repository. https://doi.org/10.24432/C50S4B"
TIMEOUT_SECONDS = 90

FEATURES = [
    "Area", "Perimeter", "MajorAxisLength", "MinorAxisLength", "AspectRation", "Eccentricity", "ConvexArea",
    "EquivDiameter", "Extent", "Solidity", "roundness", "Compactness", "ShapeFactor1", "ShapeFactor2",
    "ShapeFactor3", "ShapeFactor4",
]
TARGET = "Class"
EXPECTED_CLASSES = {"SEKER", "BARBUNYA", "BOMBAY", "CALI", "DERMASON", "HOROZ", "SIRA"}
# The UCI file spells two headers unusually; accept common variants and normalise.
ALIASES = {"AspectRatio": "AspectRation", "Roundness": "roundness", "class": "Class"}


class DataError(RuntimeError):
    """Raised with a human-readable recovery hint when data is missing or malformed."""


def fetch(force: bool = False) -> Path:
    if RAW_FILE.exists() and not force:
        return RAW_FILE
    print(f"Downloading {SOURCE_URL} ...", flush=True)
    request = urllib.request.Request(SOURCE_URL, headers={"User-Agent": "dataset-starter-packs/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            payload = response.read()
    except (urllib.error.URLError, TimeoutError) as exc:
        raise DataError(
            f"Could not download {SOURCE_URL} ({exc}).\nRecovery: download the ZIP from {DATASET_PAGE}, "
            f"open Dry_Bean_Dataset.xlsx, save it as CSV at {RAW_FILE}, then run real mode again."
        ) from exc
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = [n for n in archive.namelist() if n.lower().endswith(".xlsx")]
        if not names:
            raise DataError("Archive has no .xlsx file - the upstream layout may have changed.")
        try:
            frame = pd.read_excel(io.BytesIO(archive.read(names[0])))
        except ImportError as exc:
            raise DataError("Reading the .xlsx needs openpyxl: pip install openpyxl") from exc
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    frame.to_csv(RAW_FILE, index=False)
    meta = {
        "source_url": SOURCE_URL,
        "dataset_page": DATASET_PAGE,
        "file_in_archive": names[0],
        "retrieved_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "archive_sha256": hashlib.sha256(payload).hexdigest(),
        "rows": int(len(frame)),
        "license": "CC BY 4.0",
        "citation": CITATION,
    }
    SOURCE_META.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"Saved {len(frame):,} rows to {RAW_FILE}", flush=True)
    return RAW_FILE


def validate(df: pd.DataFrame) -> pd.DataFrame:
    df = df.rename(columns={k: v for k, v in ALIASES.items() if k in df.columns})
    missing = [c for c in FEATURES + [TARGET] if c not in df.columns]
    if missing:
        raise DataError(f"Required column(s) missing: {', '.join(missing)}")
    out = df[FEATURES + [TARGET]].copy()
    for col in FEATURES:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    if out[FEATURES].isna().any().any():
        raise DataError("Feature columns contain missing or non-numeric values.")
    out[TARGET] = out[TARGET].astype(str).str.strip().str.upper()
    unknown = set(out[TARGET]) - EXPECTED_CLASSES
    if unknown:
        raise DataError(f"Unexpected class label(s): {sorted(unknown)}")
    return out.reset_index(drop=True)


def load(mode: str = "sample", fetch_if_missing: bool = True) -> pd.DataFrame:
    if mode == "sample":
        if not FIXTURE_FILE.exists():
            raise DataError(f"Expected fixture {FIXTURE_FILE}. Run fixtures/make_fixture.py.")
        return validate(pd.read_csv(FIXTURE_FILE))
    if mode != "real":
        raise DataError(f"Unknown mode {mode!r}.")
    if not RAW_FILE.exists():
        if not fetch_if_missing:
            raise DataError(f"Expected dry_bean.csv in {RAW_DIR}. Run `python load_data.py --fetch` first.")
        fetch()
    return validate(pd.read_csv(RAW_FILE))


def provenance(mode: str) -> dict:
    if mode == "sample":
        return {"kind": "synthetic fixture", "file": "fixtures/dry_bean_sample.csv",
                "note": "Invented shape measurements. BOMBAY is deliberately rare."}
    return json.loads(SOURCE_META.read_text(encoding="utf-8")) if SOURCE_META.exists() else {"kind": "real"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--mode", default="sample", choices=["sample", "real"])
    args = parser.parse_args()
    if args.fetch:
        fetch(force=args.force)
        args.mode = "real"
    df = load(args.mode)
    print(df[TARGET].value_counts())
