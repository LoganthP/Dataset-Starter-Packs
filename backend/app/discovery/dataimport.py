"""On-demand file access (never during search): list a dataset's downloadable files, preview a few rows,
and the read helpers used by analysis runs (analysis.py). Archives are handled by archive.py and the format registry.
Only files the dataset lists can be downloaded, never arbitrary URLs.
"""
from __future__ import annotations

import io
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .adapters import huggingface
from .adapters.http import AdapterError
from .limits import MAX_TRANSFER_BYTES as MAX_BYTES  # noqa: E402  one limit for every transfer (limits.py)

SUPPORTED = (".csv", ".tsv", ".tab", ".txt", ".parquet", ".json", ".jsonl", ".ndjson", ".geojson", ".zip", ".gz", ".xlsx")


class ImportError_(RuntimeError):
    pass


def _ext_format(name: str) -> str | None:
    n = name.lower().split("?")[0]
    for ext, fmt in ((".parquet", "parquet"), (".csv.gz", "csv"), (".csv", "csv"), (".tsv", "tsv"), (".tab", "tsv"), (".txt", "csv"),
                     (".jsonl", "json"), (".ndjson", "json"), (".geojson", "json"), (".json", "json"), (".zip", "zip"), (".xlsx", "xlsx")):
        if n.endswith(ext):
            return fmt
    return None


def list_files(rec: dict) -> list[dict]:
    """Analyzable files only (used by preview). The full resolved list, with unsupported files, is resolve.resolve()."""
    from .resolve import resolve

    try:
        return [f for f in resolve(rec)["files"] if f["supported"]]
    except AdapterError as exc:
        raise ImportError_(str(exc)) from exc


def preview(rec: dict) -> dict:
    if rec.get("previewProvider") == "huggingface":
        try:
            return {"kind": "huggingface", **huggingface.preview(rec["providerId"])}
        except (AdapterError, ValueError, KeyError) as exc:
            raise ImportError_(f"Hugging Face preview unavailable: {exc}") from exc
    for f in list_files(rec):
        if f["format"] in ("csv", "tsv") and not f["url"].endswith(".gz"):
            req = urllib.request.Request(f["url"], headers={"Range": "bytes=0-262143", "User-Agent": "dataset-starter-packs/0.3"})
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    chunk = resp.read(262144).decode("utf-8", errors="replace")
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                raise ImportError_(f"Couldn't read {f['url']}: {exc}") from exc
            import pandas as pd

            lines = chunk.splitlines()[:-1] or chunk.splitlines()
            sep = "\t" if f["format"] == "tsv" or lines[0].count("\t") > lines[0].count(",") else ("," if lines[0].count(",") >= lines[0].count(";") else ";")
            df = pd.read_csv(io.StringIO("\n".join(lines[:21])), sep=sep, on_bad_lines="skip")
            return {"kind": "csv-head", "file": f["name"] or f["url"], "columns": [{"name": str(c), "type": str(t)} for c, t in df.dtypes.items()],
                    "rows": json.loads(df.head(20).to_json(orient="values", date_format="iso")), "source": f["url"]}
    raise ImportError_("This source has no row preview. Open the source page, or import a file if one is listed.")


# ---------------------------------------------------------------- download / unzip / read helpers
def _download(url: str, dest: Path) -> int:
    headers = {"User-Agent": "dataset-starter-packs/0.5"}
    if urllib.parse.urlparse(url).netloc == "www.kaggle.com":  # Kaggle API downloads use the server's credentials
        from .adapters.kaggle import _auth_header

        headers.update(_auth_header())
    from .. import blob

    if blob.is_blob_url(url):  # a private upload in this app's Vercel Blob store
        headers.update(blob.auth_headers())
    req = urllib.request.Request(url, headers=headers)
    size = 0
    try:
        with urllib.request.urlopen(req, timeout=60) as resp, open(dest, "wb") as out:
            declared = int(resp.headers.get("Content-Length") or 0)
            if declared > MAX_BYTES:
                raise ImportError_(f"File is {declared / 1e6:.0f} MB; the limit is {MAX_BYTES / 1e6:.0f} MB (DSP_MAX_TRANSFER_BYTES).")
            while chunk := resp.read(1 << 20):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise ImportError_(f"File exceeds the {MAX_BYTES / 1e6:.0f} MB limit (DSP_MAX_TRANSFER_BYTES).")
                out.write(chunk)
    except urllib.error.HTTPError as exc:
        hint = " The provider needs you to sign in - download it in your browser and upload it here." if exc.code in (401, 403) else ""
        raise ImportError_(f"Download failed: HTTP {exc.code}.{hint}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ImportError_(f"Download failed: {getattr(exc, 'reason', exc)}") from exc
    return size


def xlsx_sheets(path: Path) -> list[str]:
    from openpyxl import load_workbook

    wb = load_workbook(path, read_only=True)
    try:
        return list(wb.sheetnames)
    finally:
        wb.close()


def xlsx_to_csv(path: Path, sheet: str | None = None) -> Path:
    """DuckDB reads CSV/Parquet/JSON natively; Excel goes through pandas (the chosen sheet, else the first)."""
    import pandas as pd

    out = path.with_suffix(".csv")
    pd.read_excel(path, sheet_name=sheet if sheet is not None else 0).to_csv(out, index=False)
    return out


def _reader(path: Path, fmt: str) -> str:
    p = path.resolve().as_posix().replace("'", "''")
    if fmt == "parquet":
        return f"read_parquet('{p}')"
    if fmt == "json":
        return f"read_json_auto('{p}')"
    extra = ", delim='\\t'" if fmt == "tsv" else ""
    # Malformed rows are skipped rather than failing the whole file, and recorded so the report can say how many.
    # '?' and NA-style markers are read as missing (e.g. UCI household power uses '?'), so numeric columns stay numeric.
    return (f"read_csv('{p}', ignore_errors=true, store_rejects=true, sample_size=20000, "
            f"nullstr=['', '?', 'NA', 'N/A', 'NULL', 'null']{extra})")
