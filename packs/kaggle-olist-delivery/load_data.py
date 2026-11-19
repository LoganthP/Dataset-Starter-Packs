"""Data loader for the Olist e-commerce pack (DuckDB).

The upstream files are licensed CC BY-NC-SA 4.0 and are NOT committed to this repo.

* ``sample`` mode uses synthetic CSVs in ``fixtures/`` with the real column names.
* ``real`` mode expects the three Kaggle CSVs in ``data/raw/``. Get them by either:
    1. ``pip install kagglehub`` then ``python load_data.py --fetch`` (may ask for Kaggle auth), or
    2. downloading the ZIP from https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce
       and running ``python load_data.py --import path/to/archive.zip`` (or uploading it in the web app).
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import shutil
import zipfile
from pathlib import Path

PACK_DIR = Path(__file__).resolve().parent
RAW_DIR = PACK_DIR / "data" / "raw"
SOURCE_META = RAW_DIR / "source.json"
FIXTURE_DIR = PACK_DIR / "fixtures"
KAGGLE_HANDLE = "olistbr/brazilian-ecommerce"
DATASET_PAGE = "https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce"
LICENSE = "CC BY-NC-SA 4.0"

FILES = {
    "orders": "olist_orders_dataset.csv",
    "items": "olist_order_items_dataset.csv",
    "reviews": "olist_order_reviews_dataset.csv",
}
COLUMNS = {
    "orders": ["order_id", "customer_id", "order_status", "order_purchase_timestamp", "order_approved_at",
               "order_delivered_carrier_date", "order_delivered_customer_date", "order_estimated_delivery_date"],
    "items": ["order_id", "order_item_id", "product_id", "seller_id", "shipping_limit_date", "price", "freight_value"],
    "reviews": ["review_id", "order_id", "review_score", "review_comment_title", "review_comment_message",
                "review_creation_date", "review_answer_timestamp"],
}
SAMPLE_FILES = {k: f"sample_{v}" for k, v in FILES.items()}


class DataError(RuntimeError):
    """Raised with a human-readable recovery hint when data is missing or malformed."""


def _recovery() -> str:
    return (f"Recovery: download the ZIP from {DATASET_PAGE} (free Kaggle account), then either\n"
            f"  python load_data.py --import path/to/archive.zip\n"
            f"or upload the ZIP on this pack's page in the web app, or copy {', '.join(FILES.values())} into {RAW_DIR}.")


def _write_meta(method: str, origin: str) -> None:
    meta = {
        "source": DATASET_PAGE,
        "kaggle_handle": KAGGLE_HANDLE,
        "method": method,
        "origin": origin,
        "retrieved_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "files": {name: hashlib.sha256((RAW_DIR / f).read_bytes()).hexdigest() for name, f in FILES.items()},
        "license": LICENSE,
        "terms_note": "Non-commercial use, share-alike, attribution to Olist. Do not commit these files.",
    }
    SOURCE_META.write_text(json.dumps(meta, indent=2), encoding="utf-8")


def import_files(source: str | Path) -> list[str]:
    """Copy the three needed CSVs from a ZIP or a folder into data/raw/. Returns imported file names."""
    source = Path(source)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    wanted = set(FILES.values())
    found: list[str] = []
    if source.is_file() and zipfile.is_zipfile(source):
        with zipfile.ZipFile(source) as archive:
            for member in archive.namelist():
                name = Path(member).name  # never trust paths inside the archive
                if name in wanted:
                    (RAW_DIR / name).write_bytes(archive.read(member))
                    found.append(name)
    elif source.is_dir():
        for name in wanted:
            hits = list(source.rglob(name))
            if hits:
                shutil.copyfile(hits[0], RAW_DIR / name)
                found.append(name)
    elif source.is_file() and source.name in wanted:
        shutil.copyfile(source, RAW_DIR / source.name)
        found.append(source.name)
    else:
        raise DataError(f"{source} is not a ZIP, a folder, or one of {sorted(wanted)}.")
    if all((RAW_DIR / f).exists() for f in FILES.values()):
        _write_meta("import", str(source.name))
    return sorted(set(found))


def fetch(force: bool = False) -> Path:
    """Download with kagglehub if available; otherwise explain the manual route."""
    if all((RAW_DIR / f).exists() for f in FILES.values()) and not force:
        return RAW_DIR
    try:
        import kagglehub  # optional dependency
    except ImportError as exc:
        raise DataError("kagglehub is not installed (pip install kagglehub).\n" + _recovery()) from exc
    print(f"Downloading {KAGGLE_HANDLE} with kagglehub ...", flush=True)
    try:
        path = Path(kagglehub.dataset_download(KAGGLE_HANDLE))
    except Exception as exc:  # kagglehub raises several auth/network error types
        raise DataError(f"kagglehub download failed: {exc}\nIf Kaggle asks for credentials, run "
                        f"`kagglehub.login()` or set KAGGLE_USERNAME/KAGGLE_KEY.\n" + _recovery()) from exc
    import_files(path)
    _write_meta("kagglehub", KAGGLE_HANDLE)
    return RAW_DIR


def paths(mode: str, data_dir: Path | None = None) -> dict[str, Path]:
    if mode == "sample":
        return {k: FIXTURE_DIR / v for k, v in SAMPLE_FILES.items()}
    if mode == "real":
        base = data_dir or RAW_DIR
        return {k: base / v for k, v in FILES.items()}
    if mode == "custom" and data_dir:
        return {k: data_dir / v for k, v in FILES.items()}
    raise DataError(f"Unknown mode {mode!r}.")


def connect(mode: str = "sample", data_dir: Path | None = None, fetch_if_missing: bool = True):
    """Return a DuckDB connection with validated ``orders``, ``items`` and ``reviews`` views."""
    import duckdb

    files = paths(mode, data_dir)
    if mode == "real" and not all(p.exists() for p in files.values()) and fetch_if_missing:
        fetch()
    for path in files.values():
        if not path.exists():
            raise DataError(f"Expected {path.name} in {path.parent}.\n" + (_recovery() if mode == "real" else ""))
    con = duckdb.connect()
    for name, path in files.items():
        literal = path.resolve().as_posix().replace("'", "''")  # views cannot take bound parameters
        con.execute(f"create or replace view {name} as select * from read_csv('{literal}', header=true, all_varchar=true)")
        cols = [r[0] for r in con.execute(f"describe {name}").fetchall()]
        missing = [c for c in COLUMNS[name] if c not in cols]
        if missing:
            raise DataError(f"Required column(s) missing from {path.name}: {', '.join(missing)}")
    if con.execute("select count(*) - count(distinct order_id) from orders").fetchone()[0]:
        raise DataError("orders must have one row per order_id.")
    return con


def provenance(mode: str) -> dict:
    if mode == "sample":
        return {"kind": "synthetic fixture", "files": list(SAMPLE_FILES.values()),
                "note": "Invented orders with the Olist schema. Includes multi-item orders and duplicate reviews."}
    return json.loads(SOURCE_META.read_text(encoding="utf-8")) if SOURCE_META.exists() else {"kind": "real", "license": LICENSE}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fetch", action="store_true", help="download with kagglehub")
    parser.add_argument("--import", dest="import_path", help="ZIP or folder containing the Olist CSVs")
    parser.add_argument("--mode", default="sample", choices=["sample", "real"])
    args = parser.parse_args()
    if args.import_path:
        print("Imported:", import_files(args.import_path))
        args.mode = "real"
    if args.fetch:
        fetch()
        args.mode = "real"
    con = connect(args.mode)
    for table in FILES:
        print(table, con.execute(f"select count(*) from {table}").fetchone()[0])
