"""Data loader for the NASA Exoplanet Archive pack (Planetary Systems Composite Parameters).

* ``sample`` mode reads a synthetic catalog with the same columns.
* ``real`` mode runs an ADQL query against the archive's TAP service, caches the CSV in
  ``data/raw/pscomppars.csv`` and records the exact query + retrieval date in ``source.json``.
  The table updates weekly, so always report the retrieval date with your results.

    python load_data.py --fetch
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import io
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

PACK_DIR = Path(__file__).resolve().parent
RAW_DIR = PACK_DIR / "data" / "raw"
RAW_FILE = RAW_DIR / "pscomppars.csv"
SOURCE_META = RAW_DIR / "source.json"
FIXTURE_FILE = PACK_DIR / "fixtures" / "pscomppars_sample.csv"

TAP_URL = "https://exoplanetarchive.ipac.caltech.edu/TAP/sync"
TABLE = "pscomppars"
DOI = "10.26133/NEA13"
COLUMNS: dict[str, str] = {
    "pl_name": "str",
    "hostname": "str",
    "discoverymethod": "str",
    "disc_year": "int",
    "disc_facility": "str",
    "pl_rade": "float",
    "pl_orbper": "float",
    "pl_bmasse": "float",
    "sy_dist": "float",
}
QUERY = f"select {','.join(COLUMNS)} from {TABLE}"
TIMEOUT_SECONDS = 120


class DataError(RuntimeError):
    """Raised with a human-readable recovery hint when data is missing or malformed."""


def query_url(query: str = QUERY) -> str:
    return f"{TAP_URL}?{urllib.parse.urlencode({'query': query, 'format': 'csv'})}"


def fetch(force: bool = False) -> Path:
    if RAW_FILE.exists() and not force:
        return RAW_FILE
    url = query_url()
    print(f"Querying NASA Exoplanet Archive TAP: {QUERY}", flush=True)
    request = urllib.request.Request(url, headers={"User-Agent": "dataset-starter-packs/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            payload = response.read()
    except urllib.error.HTTPError as exc:
        raise DataError(f"TAP service returned HTTP {exc.code}: {exc.read()[:300]!r}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise DataError(
            f"Could not reach the Exoplanet Archive ({exc}).\nRecovery: retry later, or run the same query in the "
            f"archive's TAP web form and save the CSV as {RAW_FILE}."
        ) from exc
    if payload.lstrip().startswith(b"<"):
        raise DataError(f"TAP returned an error document instead of CSV: {payload[:300]!r}")
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    RAW_FILE.write_bytes(payload)
    rows = payload.count(b"\n") - 1
    meta = {
        "source_url": url,
        "service": TAP_URL,
        "table": TABLE,
        "query": QUERY,
        "rows": rows,
        "retrieved_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "doi": DOI,
        "citation": f"NASA Exoplanet Archive, Planetary Systems Composite Parameters, doi:{DOI}, accessed "
                    f"{dt.date.today().isoformat()}",
    }
    SOURCE_META.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"Saved {rows:,} planets to {RAW_FILE}", flush=True)
    return RAW_FILE


def validate(df: pd.DataFrame) -> pd.DataFrame:
    missing = [c for c in COLUMNS if c not in df.columns]
    if missing:
        raise DataError(f"Required column(s) missing: {', '.join(missing)}")
    out = df[list(COLUMNS)].copy()
    for col, kind in COLUMNS.items():
        if kind in {"int", "float"}:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    if out["pl_name"].isna().any() or out["pl_name"].duplicated().any():
        raise DataError("pl_name must be present and unique (one row per planet in pscomppars).")
    if out["discoverymethod"].isna().any():
        raise DataError("discoverymethod has missing values.")
    for col in ("pl_rade", "pl_orbper"):
        if (out[col] <= 0).any():
            raise DataError(f"{col} contains non-positive values; cannot plot on a log scale.")
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
            raise DataError(f"Expected pscomppars.csv in {RAW_DIR}. Run `python load_data.py --fetch` first.")
        fetch()
    return validate(pd.read_csv(io.BytesIO(RAW_FILE.read_bytes())))


def provenance(mode: str) -> dict:
    if mode == "sample":
        return {"kind": "synthetic fixture", "file": "fixtures/pscomppars_sample.csv",
                "note": "Invented planets. Distributions are illustrative only."}
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
    print(f"{len(df):,} planets; methods:\n{df['discoverymethod'].value_counts()}")
