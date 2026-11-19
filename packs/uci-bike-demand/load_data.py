"""Data loader for the UCI Bike Sharing pack.

Two modes share the same validation path:

* ``sample`` (default) reads the synthetic fixture in ``fixtures/`` - no network needed.
* ``real`` downloads the official UCI archive once, caches ``hour.csv`` in ``data/raw/``
  and records provenance (URL, retrieval date, SHA-256) in ``data/raw/source.json``.

Run ``python load_data.py --fetch`` to download the real data ahead of time.
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
RAW_FILE = RAW_DIR / "hour.csv"
SOURCE_META = RAW_DIR / "source.json"
FIXTURE_FILE = PACK_DIR / "fixtures" / "hour_sample.csv"

SOURCE_URL = "https://archive.ics.uci.edu/static/public/275/bike+sharing+dataset.zip"
DATASET_PAGE = "https://archive.ics.uci.edu/dataset/275/bike+sharing+dataset"
CITATION = "Fanaee-T, H. (2013). Bike Sharing [Dataset]. UCI Machine Learning Repository. https://doi.org/10.24432/C5W894"
TIMEOUT_SECONDS = 60

EXPECTED_COLUMNS: dict[str, str] = {
    "instant": "int",
    "dteday": "date",
    "season": "int",
    "yr": "int",
    "mnth": "int",
    "hr": "int",
    "holiday": "int",
    "weekday": "int",
    "workingday": "int",
    "weathersit": "int",
    "temp": "float",
    "atemp": "float",
    "hum": "float",
    "windspeed": "float",
    "casual": "int",
    "registered": "int",
    "cnt": "int",
}

# Columns that are components of the target. Using them as features leaks the answer.
LEAKY_COLUMNS = ("casual", "registered")
TARGET = "cnt"


class DataError(RuntimeError):
    """Raised with a human-readable recovery hint when data is missing or malformed."""


def _download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "dataset-starter-packs/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return response.read()
    except (urllib.error.URLError, TimeoutError) as exc:
        raise DataError(
            f"Could not download {url} ({exc}).\n"
            f"Recovery: download the ZIP manually from {DATASET_PAGE}, extract hour.csv "
            f"and place it at {RAW_FILE}. Then run real mode again."
        ) from exc


def fetch(force: bool = False) -> Path:
    """Download the official archive and cache hour.csv. Returns the cached path."""
    if RAW_FILE.exists() and not force:
        return RAW_FILE
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {SOURCE_URL} ...", flush=True)
    payload = _download(SOURCE_URL)
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = [n for n in archive.namelist() if n.endswith("hour.csv")]
        if not names:
            raise DataError("The downloaded archive does not contain hour.csv. The upstream layout may have changed.")
        RAW_FILE.write_bytes(archive.read(names[0]))
    meta = {
        "source_url": SOURCE_URL,
        "dataset_page": DATASET_PAGE,
        "file": "hour.csv",
        "retrieved_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "archive_sha256": hashlib.sha256(payload).hexdigest(),
        "file_sha256": hashlib.sha256(RAW_FILE.read_bytes()).hexdigest(),
        "license": "CC BY 4.0",
        "citation": CITATION,
    }
    SOURCE_META.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"Saved {RAW_FILE} ({RAW_FILE.stat().st_size:,} bytes)", flush=True)
    return RAW_FILE


def validate(df: pd.DataFrame) -> pd.DataFrame:
    """Check schema and invariants. Returns a typed copy or raises DataError."""
    missing = [c for c in EXPECTED_COLUMNS if c not in df.columns]
    if missing:
        raise DataError(f"Required column(s) missing: {', '.join(missing)}")
    out = df.copy()
    out["dteday"] = pd.to_datetime(out["dteday"], errors="coerce")
    if out["dteday"].isna().any():
        raise DataError("Column dteday contains values that are not dates (expected YYYY-MM-DD).")
    for col, kind in EXPECTED_COLUMNS.items():
        if kind in {"int", "float"}:
            out[col] = pd.to_numeric(out[col], errors="coerce")
            if out[col].isna().any():
                raise DataError(f"Column {col} has non-numeric or missing values.")
    if not out["hr"].between(0, 23).all():
        raise DataError("Column hr must be between 0 and 23.")
    if (out["casual"] + out["registered"] != out["cnt"]).any():
        raise DataError("Invariant broken: casual + registered must equal cnt on every row.")
    out["timestamp"] = out["dteday"] + pd.to_timedelta(out["hr"], unit="h")
    if out["timestamp"].duplicated().any():
        raise DataError("Duplicate (dteday, hr) rows found.")
    return out.sort_values("timestamp").reset_index(drop=True)


def load(mode: str = "sample", fetch_if_missing: bool = True) -> pd.DataFrame:
    """Load and validate data for ``mode`` ('sample' or 'real')."""
    if mode == "sample":
        if not FIXTURE_FILE.exists():
            raise DataError(f"Expected fixture at {FIXTURE_FILE}. Re-clone the pack or run fixtures/make_fixture.py.")
        return validate(pd.read_csv(FIXTURE_FILE))
    if mode != "real":
        raise DataError(f"Unknown mode {mode!r}. Use 'sample' or 'real'.")
    if not RAW_FILE.exists():
        if not fetch_if_missing:
            raise DataError(f"Expected hour.csv in {RAW_DIR}. Run `python load_data.py --fetch` first.")
        fetch()
    return validate(pd.read_csv(RAW_FILE))


def provenance(mode: str) -> dict:
    if mode == "sample":
        return {"kind": "synthetic fixture", "file": str(FIXTURE_FILE.relative_to(PACK_DIR)),
                "note": "Invented data with the real schema. Scores are NOT comparable to real results."}
    if SOURCE_META.exists():
        return json.loads(SOURCE_META.read_text(encoding="utf-8"))
    return {"kind": "real", "file": str(RAW_FILE), "note": "Placed manually; no download metadata recorded."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fetch", action="store_true", help="download the real dataset into data/raw/")
    parser.add_argument("--force", action="store_true", help="re-download even if cached")
    parser.add_argument("--mode", default="sample", choices=["sample", "real"])
    args = parser.parse_args()
    if args.fetch:
        fetch(force=args.force)
    frame = load(args.mode)
    print(f"{args.mode}: {len(frame):,} rows, {frame['timestamp'].min()} -> {frame['timestamp'].max()}")
