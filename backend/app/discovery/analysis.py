"""Dataset analysis runs: download (or accept) one file, profile it with DuckDB, keep the report.

A run is persisted in SQLite with the dataset id, the exact file/URL analyzed, the source's license
and version at that moment, a step log, and the report. Re-analyzing creates a new run; the dataset's
card always shows the latest successful one. Facts the file proves (columns, types, date range)
become *verified* evidence for that dataset.

Sample runs read bounded subsets. Full runs profile all fetched rows and verify completeness for paged sources.
"""
from __future__ import annotations

import contextvars
import csv
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
import time
import urllib.parse
import uuid
from pathlib import Path

from .. import config, durable
from . import archive as archive_mod
from . import cache as cache_mod
from . import fetch as fetch_mod
from . import insights as insights_mod
from . import limits, store
from .adapters.common import concepts_for
from .dataimport import ImportError_, _ext_format, _reader
from .fetch import FetchError
from .formats import registry

RUNS_DIR = config.STATE_DIR / "analyses"
SODA_PAGE_ROWS = 25_000
SODA_PAGE_BYTES = 32 * 2**20
SODA_MAX_BYTES = int(float(os.getenv("DSP_SODA_FULL_MAX_MB", "2048")) * 2**20)
# "Analyze sample" (the default action): a bounded read so the first click returns insights quickly.
QUICK_ROWS = int(os.getenv("DSP_QUICK_SAMPLE_ROWS", "1000"))
QUICK_DEADLINE_S = float(os.getenv("DSP_SAMPLE_DEADLINE_SECONDS", "60"))
QUICK_MAX_BYTES = limits.QUICK_MAX_BYTES  # whole-file formats (Parquet, ZIP, Excel) in sample mode
MAX_BYTES = limits.MAX_TRANSFER_BYTES  # uploads and provider downloads, ZIPs included (DSP_MAX_TRANSFER_BYTES, default 2 GB)
FULL_DEADLINE_S = float(os.getenv("DSP_FULL_DEADLINE_SECONDS", "1800"))
IDLE_S = float(os.getenv("DSP_DOWNLOAD_IDLE_SECONDS", "30"))  # connect timeout and longest silence while downloading
# Shown as Fetching -> Inspecting -> Analyzing -> Saving ("charting" is part of Analyzing).
STAGES = ["resolving", "downloading", "extracting", "profiling", "charting", "saving"]

# A queued/running run older than this was interrupted (restart, serverless timeout): every run has its own deadline.
STALE_MINUTES = int(FULL_DEADLINE_S // 60) + 10


def _now() -> str:
    # Microseconds so two runs started in the same second still order correctly ("latest analysis").
    return dt.datetime.now(dt.UTC).isoformat(timespec="microseconds")


def _row(r) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    for k in ("source", "report", "progress", "params", "error_detail", "job", "summary"):
        d[k] = json.loads(d[k]) if d.get(k) else None
    return d


def _update(run_id: str, **fields) -> None:
    durable.execute(f"update analysis_runs set {', '.join(f'{k}=?' for k in fields)} where id=?",
                    (*[json.dumps(v) if k in ("source", "report", "progress", "params", "error_detail", "job", "summary") and v is not None else v
                       for k, v in fields.items()], run_id))


def _log(run_id: str, line: str) -> None:
    durable.execute("update analysis_runs set log = log || ? where id=?", (f"{_now()[11:19]}  {line}\n", run_id))


def _expire_stale() -> None:
    if RUN_MODE == "queue":
        # Jobs wait for a worker as long as it takes (up to DSP_QUEUE_MAX_AGE_HOURS); only runs whose worker vanished are touched.
        from .. import queueing

        queueing.reap_throttled()
        return
    cutoff = (dt.datetime.now(dt.UTC) - dt.timedelta(minutes=STALE_MINUTES)).isoformat(timespec="seconds")
    durable.execute("update analysis_runs set status='failed', finished_at=?, error_kind='interrupted', error=? "
                    "where status in ('queued','running') and created_at < ?",
                    (_now(), "Interrupted: the server stopped before this analysis finished. Run it again.", cutoff))


ANY = object()  # internal callers (workers, tests) see every run
_CTX = object()  # "whoever is making this request" (set per request by main.py's middleware)
VIEWER: contextvars.ContextVar = contextvars.ContextVar("analysis_viewer", default=ANY)


def _who(user):
    return VIEWER.get() if user is _CTX else user


def visible(run: dict | None, user) -> dict | None:
    """Runs started by a signed-in user belong to that user; anonymous runs are shared."""
    if run is None or user is ANY or not run.get("owner") or run.get("owner") == user:
        return run
    return None


def get(run_id: str, user=_CTX) -> dict | None:
    user = _who(user)
    run = _row(durable.one("select * from analysis_runs where id=?", (run_id,)))
    if run and run["status"] in ("queued", "running"):
        _expire_stale()
        run = _row(durable.one("select * from analysis_runs where id=?", (run_id,)))
    return visible(run, user)


def _owner_clause(user) -> tuple[str, tuple]:
    user = _who(user)
    if user is ANY:
        return "1=1", ()
    if user:
        return "(owner is null or owner=?)", (user,)
    return "owner is null", ()


def list_runs(dataset_id: str | None = None, limit: int = 200, user=_CTX) -> list[dict]:
    oc, op = _owner_clause(user)
    # Lists never need the report or log: leave the big JSON columns out of the query.
    cols = ("id, dataset_id, status, created_at, finished_at, file_name, file_url, file_format, file_bytes, file_sha256, source, error, mode, "
            "stage, error_kind, error_detail, progress, params, owner, worker, summary")
    q = f"select {cols} from analysis_runs where {oc}" + (" and dataset_id=?" if dataset_id else "") + " order by created_at desc limit ?"
    return [_row(r) for r in durable.query(q, (*op, dataset_id, limit) if dataset_id else (*op, limit))]


def scope_label(rep: dict) -> str:
    """How much of the source a report covers, in the words every view uses."""
    if (rep.get("scope") or {}).get("label"):
        return rep["scope"]["label"]
    if rep.get("kind") == "inspection" or rep.get("coverage") == "inspection":
        return "Inspection only"
    if rep.get("coverage") != "full":
        return "Sample"
    params = rep.get("params") or {}
    return "Full selected date range" if params.get("dateFrom") or params.get("dateTo") else "Full dataset"


def _kind_preview(rep: dict) -> dict | None:
    """Card chart for non-table reports: class balance, a trajectory component, or SINEX estimate types."""
    im, tr, sx = rep.get("images"), rep.get("trajectory"), rep.get("sinex")
    if im:
        pairs = im.get("class_images") or im.get("objects_by_class") or []
        if pairs:
            what = "Images per class" if im.get("class_images") else "Objects per class"
            return {"label": f"{what}: " + ", ".join(f"{k} {v:,}" for k, v in pairs[:3]), "values": [v for _, v in pairs[:12]], "kind": "bars"}
    if tr and tr.get("series"):
        s = next((x for x in tr["series"] if x["column"] == "semi_major_axis"), tr["series"][0])
        pts = s["points"][:: max(1, len(s["points"]) // 60)]
        return {"label": f"{s['column']} over time, {len(tr.get('maneuvers') or [])} maneuvers", "values": [v for _, v in pts], "kind": "line"}
    if sx and sx.get("estimate_types"):
        return {"label": "Estimates by type: " + ", ".join(k for k, _ in sx["estimate_types"][:6]), "values": [v for _, v in sx["estimate_types"][:12]], "kind": "bars"}
    return None


def _card(rep: dict, mode: str | None) -> dict:
    """The compact summary cards, Discover and Curated Packs show. Saved with the run (column `summary`)."""
    return {"coverage": rep.get("coverage"), "rows": rep.get("rows_total"), "rowsAnalyzed": rep.get("rows_analyzed"),
            "columns": len(rep.get("columns", [])), "dateCoverage": rep.get("date_coverage"), "missingPct": rep.get("missing_pct"),
            "duplicates": rep.get("duplicate_rows"), "mode": mode or "full", "sampleMethod": rep.get("sample_method"), "scope": scope_label(rep),
            "scopeDetail": rep.get("scope"), "kind": rep.get("kind") or "table", "handlerLabel": rep.get("handler_label"),
            "preview": _kind_preview(rep) or insights_mod.card_preview(rep.get("insights") or {}),
            "validCoordsPct": ((rep.get("insights") or {}).get("coordinates") or {}).get("valid_pct")}


def _summary(run_id: str, rep: dict) -> dict:
    row = durable.one("select mode from analysis_runs where id=?", (run_id,))
    return _card(rep, (row or {}).get("mode"))


def latest_successful(user=_CTX) -> dict[str, dict]:
    """dataset_id -> compact summary of its latest succeeded run visible to `user` (cards and Curated Packs).
    Reads the saved summary, not the report, so listing pages stay fast however big the reports are."""
    oc, op = _owner_clause(user)
    ocb = oc.replace("owner", "b.owner")
    rows = durable.query(f"""select id, dataset_id, finished_at, file_name, summary, mode from analysis_runs a where status='succeeded' and {oc} and created_at =
                            (select max(created_at) from analysis_runs b where b.dataset_id=a.dataset_id and b.status='succeeded' and {ocb})""",
                         (*op, *op))
    out = {}
    for r in rows:
        summ = json.loads(r["summary"]) if r.get("summary") else None
        if summ is None:  # runs saved before summaries existed: build once and store
            rep = json.loads((durable.one("select report from analysis_runs where id=?", (r["id"],)) or {}).get("report") or "{}")
            summ = _card(rep, r.get("mode"))
            _update(r["id"], summary=summ)
        out[r["dataset_id"]] = {"runId": r["id"], "at": r["finished_at"], "file": r["file_name"], **summ}
    return out


# ---------------------------------------------------------------- the analysis itself
def analyze(path: Path, fmt: str, *, row_limit: int | None = None, known_total: int | None = None, partial: bool = False,
            method: str | None = None, deadline: float | None = None, on_charts=None) -> dict:
    """Profile a local file with DuckDB.

    row_limit    analyze only the first N rows (Analyze sample)
    known_total  the true row count when the file is a sample of a bigger table (e.g. Socrata count(*))
    partial      the file was cut short on purpose, so its own row count is not the table's total
    deadline     time.monotonic() value; DuckDB is interrupted when it passes
    """
    import duckdb

    spill = tempfile.TemporaryDirectory(prefix="duckdb-", dir=path.parent)
    con = duckdb.connect(config={"temp_directory": spill.name, "memory_limit": "512MB", "threads": "2",
                                 "preserve_insertion_order": "false"} if row_limit is None else {"temp_directory": spill.name})
    timer = None
    if deadline is not None:
        timer = threading.Timer(max(0.1, deadline - time.monotonic()), con.interrupt)
        timer.daemon = True
        timer.start()
    try:
        return _profile(con, path, fmt, row_limit, known_total, partial, method, on_charts)
    except duckdb.InterruptException as exc:
        raise FetchError("Timed out while profiling the file.", "timeout") from exc
    finally:
        if timer:
            timer.cancel()
        con.close()
        spill.cleanup()


def _profile(con, path: Path, fmt: str, row_limit, known_total, partial, method, on_charts=None) -> dict:
    import duckdb

    src = _reader(path, fmt)
    try:
        file_rows = con.execute(f"select count(*) from {src}").fetchone()[0]
    except duckdb.Error as exc:
        raise FetchError(f"Couldn't read the file as {fmt.upper()}: {str(exc).splitlines()[0]}", "format") from exc
    if row_limit:
        con.execute(f"create table t as select * from {src} limit {int(row_limit)}")
        total = known_total if known_total is not None else (None if partial else file_rows)
        sampled = partial or total is None or file_rows > row_limit or (known_total or 0) > row_limit
        method = method or f"first {min(row_limit, file_rows):,} rows of the file"
    else:
        total = file_rows
        sampled = False
        con.execute(f"create table t as select * from {src}")
    skipped, skip_reasons = 0, []
    if fmt in ("csv", "tsv"):
        try:  # rows DuckDB couldn't parse (wrong column count, bad quoting) were skipped by ignore_errors
            skipped = con.execute("select count(distinct line) from reject_errors").fetchone()[0]
            skip_reasons = [f"{r[0].lower()} ({r[1]:,})" for r in
                            con.execute("select error_type, count(distinct line) from reject_errors group by 1 order by 2 desc limit 3").fetchall()]
        except duckdb.Error:
            pass
    n = con.execute("select count(*) from t").fetchone()[0]
    cols = con.execute("describe t").fetchall()
    q = lambda name: '"' + name.replace('"', '""') + '"'  # noqa: E731
    try:
        distinct_rows = con.execute("select count(*) from (select distinct * from t)").fetchone()[0]
        duplicates = n - distinct_rows
    except duckdb.Error:
        duplicates = None  # nested types can't be compared
    columns, cells_missing = [], 0
    for name, ctype, *_ in cols:
        t = ctype.upper()
        nonnull, approx_distinct = con.execute(f"select count({q(name)}), approx_count_distinct({q(name)}) from t").fetchone()
        missing = n - nonnull
        approx_distinct = min(approx_distinct or 0, nonnull)  # HyperLogLog can overshoot slightly
        cells_missing += missing
        info = {"name": name, "type": t, "missing": missing, "missing_pct": round(100 * missing / n, 2) if n else 0.0,
                "distinct": approx_distinct, "kind": "text"}
        is_time = any(k in t for k in ("DATE", "TIMESTAMP")) or t == "TIME"
        concepts, _ = concepts_for(name, "timestamp" if is_time else t.lower())
        if any(k in t for k in ("INT", "DOUBLE", "FLOAT", "DECIMAL", "REAL", "HUGEINT")) and not is_time:
            mn, mx, mean, med, sd = con.execute(
                f"select min({q(name)}), max({q(name)}), avg({q(name)}), approx_quantile({q(name)}, 0.5), stddev_samp({q(name)}) from t").fetchone()
            info.update({"kind": "numeric", "min": mn, "max": mx, "mean": None if mean is None else round(float(mean), 4),
                         "median": med, "std": None if sd is None else round(float(sd), 4)})
        elif is_time or (t == "VARCHAR" and "timestamp" in concepts):
            expr = q(name) if is_time else f"try_cast({q(name)} as timestamp)"
            parsed, mn, mx = con.execute(f"select count({expr}), min({expr}), max({expr}) from t").fetchone()
            if is_time or (nonnull and parsed >= 0.9 * nonnull):
                info.update({"kind": "datetime", "min": str(mn), "max": str(mx), "parsed_as": None if is_time else "timestamp"})
                if "timestamp" not in concepts:
                    concepts.append("timestamp")
            else:
                concepts = [c for c in concepts if c != "timestamp"]
        elif t == "BOOLEAN":
            info["kind"] = "boolean"
        if info["kind"] == "text" and approx_distinct and approx_distinct <= 20:
            info["top"] = [[str(v), c] for v, c in con.execute(
                f"select {q(name)}, count(*) c from t where {q(name)} is not null group by 1 order by c desc limit 5").fetchall()]
        if "latlon" in concepts and not (info.get("kind") == "numeric" and info["min"] is not None and -180 <= info["min"] and info["max"] <= 180):
            concepts.remove("latlon")
        info["concepts"] = concepts
        columns.append(info)
    times = [c for c in columns if c["kind"] == "datetime" and c.get("min") not in (None, "None")]
    date_cov = None
    if times:
        best = min(times, key=lambda c: c["missing"])
        date_cov = {"column": best["name"], "min": best["min"][:10], "max": best["max"][:10]}
    preview = con.execute("select * from t limit 20").fetchall()
    report = {
        "coverage": "sample" if sampled else "full",
        "sample_method": method if sampled else None,
        "rows_total": total, "rows_analyzed": n, "columns": columns,
        "rows_skipped": skipped, "skip_reasons": skip_reasons,
        "duplicate_rows": duplicates, "duplicate_pct": round(100 * duplicates / n, 2) if duplicates is not None and n else None,
        "missing_pct": round(100 * cells_missing / (n * len(columns)), 2) if n and columns else 0.0,
        "date_coverage": date_cov,
        "preview": [[None if v is None else (v if isinstance(v, (int, float, bool)) else str(v)) for v in r] for r in preview],
    }
    if on_charts:
        on_charts()
    try:  # charts are a bonus: a failure here never fails the analysis
        report["insights"] = insights_mod.compute(con, report)
    except duckdb.InterruptException:
        raise
    except Exception as exc:  # noqa: BLE001
        report["insights"] = {"error": f"{type(exc).__name__}: {exc}", "findings": []}
    return report


def _overlay(run: dict, report: dict) -> dict:
    scope = "a sample of" if report["coverage"] == "sample" else "the full"
    ev = f"Analysis {run['id']} of {scope} file {run['file_name']} ({(run['finished_at'] or _now())[:10]})"
    ov = {"importId": run["id"], "file": run["file_name"], "at": run["finished_at"], "evidence": ev, "formats": [run["file_format"]],
          "fields": [{"name": c["name"], "type": c["type"], "concepts": c["concepts"], "level": "record", "status": "verified", "evidence": ev,
                      "description": f"{c['missing_pct']}% missing in the analyzed rows"} for c in report["columns"]]}
    if report.get("date_coverage"):
        d = report["date_coverage"]
        ov["temporal"] = {"start": d["min"], "end": d["max"], "ongoing": False, "status": "verified", "evidence": ev,
                          "note": f"Measured from `{d['column']}` in {scope} analyzed file; other files or later releases may differ."}
    return ov


def _source_snapshot(rec: dict) -> dict:
    lic = rec.get("license") or {}
    return {"title": rec["title"], "provider": rec["provider"], "canonicalUrl": rec["canonicalUrl"], "license": lic.get("name"),
            "licenseUrl": lic.get("url"), "commercialUse": lic.get("commercialUse"), "version": rec.get("sourceUpdatedAt"), "doi": rec.get("doi")}


def _create(rec: dict, file_name: str, file_url: str | None, mode: str, params: dict | None = None, owner: str | None = None) -> str:
    run_id = uuid.uuid4().hex[:12]
    durable.execute("insert into analysis_runs (id, dataset_id, status, created_at, file_name, file_url, source, mode, stage, params, owner) "
                    "values (?,?,?,?,?,?,?,?,?,?,?)",
                    (run_id, rec["id"], "queued", _now(), file_name, file_url, json.dumps(_source_snapshot(rec)), mode, "resolving",
                     json.dumps(params or {}), owner))
    return run_id


def request_cancel(run_id: str) -> None:
    durable.execute("update analysis_runs set cancel_requested=1 where id=? and status in ('queued','running')", (run_id,))


def _check_cancel(run_id: str) -> None:
    row = durable.one("select cancel_requested from analysis_runs where id=?", (run_id,))
    if row and row["cancel_requested"]:
        raise FetchError("Stopped before it finished. The previous successful report is unchanged.", "cancelled")


def _socrata_where(f: dict, params: dict) -> str | None:
    """SoQL $where for a date range on a Socrata date field."""
    field, a, b = params.get("dateField"), params.get("dateFrom"), params.get("dateTo")
    if not (field and (a or b)) or field not in (f.get("date_fields") or []):
        return None
    lo = f"'{a}T00:00:00'" if a else "'1800-01-01T00:00:00'"
    hi = f"'{b}T23:59:59'" if b else "'2999-12-31T23:59:59'"
    return f"{field} between {lo} and {hi}"


def _with_where(url: str, where: str | None) -> str:
    if not where:
        return url
    return url + ("&" if "?" in url else "?") + "$where=" + urllib.parse.quote(where)


def plan_fetch(f: dict, mode: str, params: dict) -> dict:
    """What a run will request: URL, the row-limited sample or the full table, the count URL and the method text."""
    where = _socrata_where(f, params)
    rng = f" between {params.get('dateFrom') or 'the start'} and {params.get('dateTo') or 'the end'} ({params.get('dateField')})" if where else ""
    if f.get("sample_url"):
        count = _with_where(f["count_url"], where) if f.get("count_url") else None
        if mode == "sample":
            return {"url": _with_where(f["sample_url"].replace("{n}", str(QUICK_ROWS)), where), "count_url": count, "stop": None,
                    "method": f["sample_method"].replace("{n}", f"{QUICK_ROWS:,}") + rng}
        return {"url": _with_where(f["resource_url"] + "?$order=:id", where), "count_url": count,
                "stop": None, "method": None, "paged": bool(count)}
    fmt = f.get("format")
    stop = (QUICK_ROWS + 1 if fmt != "json" else QUICK_ROWS) if mode == "sample" and fmt in ("csv", "tsv", "json") else None
    return {"url": f["url"], "count_url": None, "stop": stop, "method": None}


def _stage(run_id: str, stage: str, line: str | None = None) -> None:
    _update(run_id, stage=stage)
    if line:
        _log(run_id, line)


def _socrata_count(fetch: dict, timeout: float | None = None) -> int | None:
    try:
        from .adapters.http import get_json

        data = get_json(fetch["count_url"], timeout=timeout)
        val = next(iter((data[0] if data else {}).values()), None)
        return int(val) if val is not None else None
    except Exception:  # samples can still run when their source total is unavailable
        return None


def _download_socrata(run_id: str, plan: dict, path: Path, total: int | None, deadline: float) -> int:
    """Stage ordered CSV pages ($order=:id, $limit/$offset, the same $where as the count) on disk and verify
    completeness before any full report is published. Returns the number of rows written."""
    if total is None or total < 0:
        raise FetchError("Couldn't get the source row count, so a complete full run can't be verified. Retry later, or run a sample.", "network")
    page = path.with_suffix(".page")
    offset, bytes_read, header, logged = 0, 0, None, 0

    def on_bytes(done: int, _total: int | None) -> None:  # cancel and deadline are honoured inside a page too
        _check_cancel(run_id)

    try:
        with path.open("w", encoding="utf-8", newline="") as out:
            writer = csv.writer(out)
            while offset < total or header is None:
                _check_cancel(run_id)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise FetchError(f"Timed out after fetching {offset:,} of {total:,} rows. Choose a date range for a smaller full run.", "timeout")
                limit = min(SODA_PAGE_ROWS, max(1, total - offset))
                url = f"{plan['url']}{'&' if '?' in plan['url'] else '?'}$limit={limit}&$offset={offset}"
                got = fetch_mod.download(url, page, max_bytes=SODA_PAGE_BYTES, deadline=deadline, idle=min(IDLE_S, remaining), progress=on_bytes)
                if got.get("truncated"):
                    raise FetchError(f"A {limit:,}-row page was larger than {SODA_PAGE_BYTES // 2**20} MiB and was cut off. Retry the run.", "network")
                bytes_read += got["bytes"]
                if bytes_read > SODA_MAX_BYTES:
                    raise FetchError(f"The full table is over the {SODA_MAX_BYTES // 2**20:,} MiB staging budget (DSP_SODA_FULL_MAX_MB) after "
                                     f"{offset:,} of {total:,} rows. Choose a date range.", "too_large")
                with page.open(encoding="utf-8-sig", newline="") as inp:
                    reader = csv.reader(inp, strict=True)
                    names = next(reader, None)
                    if not names or (header is not None and names != header):
                        raise FetchError("The source returned a missing or changed CSV header. Retry the run.", "network")
                    if header is None:
                        header = names
                        writer.writerow(header)
                    rows = 0
                    for row in reader:
                        if len(row) != len(header):
                            raise FetchError(f"Row {offset + rows + 1:,} has {len(row)} fields instead of {len(header)}. Retry the run.", "network")
                        writer.writerow(row)
                        rows += 1
                expected = min(limit, total - offset)
                if rows != expected:
                    raise FetchError(f"The page at row {offset:,} returned {rows:,} rows instead of {expected:,}. "
                                     "No full report was published. Retry the run.", "network")
                offset += rows
                _update(run_id, progress={"rows": offset, "row_total": total, "bytes": bytes_read, "total": None})
                if total and (offset - logged >= total / 10 or offset == total):
                    logged = offset
                    _log(run_id, f"Fetched {offset:,} of {total:,} rows ({100 * offset / total:.0f}%, {bytes_read / 2**20:,.1f} MB)")
                if total == 0:
                    break
        after = _socrata_count(plan, timeout=max(0.1, min(10, deadline - time.monotonic())))
        if after != total:
            raise FetchError(f"The source changed while it was being read ({total:,} rows at the start, "
                             f"{'unknown' if after is None else f'{after:,}'} at the end). No full report was published. Retry the run.", "network")
        return offset
    except (csv.Error, UnicodeError) as exc:
        raise FetchError("The source returned an invalid CSV page. Retry the run.", "network") from exc
    finally:
        page.unlink(missing_ok=True)


def _auth_for(run: dict | None, url: str) -> dict | None:
    """Per-user credentials for this file (a connected Kaggle account), looked up when the run executes."""
    from .. import kaggle_connect

    if not run or not run.get("owner") or not kaggle_connect.is_kaggle_url(url):
        return None

    return kaggle_connect.auth_headers(run["owner"])


def _progress(run_id: str, phase: str, done: int, total: int | None, unit: str, **extra) -> None:
    """Current phase counters; row/byte totals from the fetch stay so the Run view can keep showing them."""
    row = durable.one("select progress from analysis_runs where id=?", (run_id,))
    prev = json.loads(row["progress"]) if row and row.get("progress") else {}
    kept = {k: prev[k] for k in ("rows", "row_total", "bytes", "total") if k in prev}
    _update(run_id, progress={**kept, "phase": phase, "done": done, "total_items": total, "unit": unit, **extra})


def _ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def detected_kind(info: dict) -> str | None:
    return info.get("detected") or info.get("kind")


RANGE_SHARE = float(os.getenv("DSP_RANGE_FETCH_MAX_SHARE", "0.5"))  # fetch members by range when they're under half the archive
RANGE_MIN_ARCHIVE = int(float(os.getenv("DSP_RANGE_MIN_ARCHIVE_BYTES", "2000000")))  # smaller archives: one plain download is cheaper


def _remote_members(run_id: str, url: str, info: dict, ckey: str | None, auth: dict | None, *, quick: bool, params: dict,
                    deadline: float, timings: dict) -> dict | None:
    """When the source is a ZIP and the server honours byte ranges, read its directory and fetch only the members the
    analysis needs. None when ranges aren't supported or the members are most of the archive (then: one full download)."""
    total = info.get("bytes_total")
    if detected_kind(info) != "zip" or not info.get("ranges") or not total or total < RANGE_MIN_ARCHIVE:
        return None
    t0 = time.monotonic()
    meta = archive_mod_cached_listing(ckey)
    rz = archive_mod.RemoteZip(url, total, auth=auth)
    try:
        listing = meta or archive_mod.inspect_remote(url, total, auth=auth, rz=rz)
    except FetchError as exc:
        _log(run_id, f"Couldn't list the archive with ranged reads ({exc}); downloading it instead")
        return None
    if not meta:
        cache_mod.write_meta(ckey, {**cache_mod.read_meta(ckey), "listing": listing, "url": url})
    timings["list_ms"] = _ms(t0)
    members = listing["members"]
    pl = registry.plan(members, sample=quick, params=params)
    selected = pl["selected"]
    need = sum(m.get("compressed") or m["size"] for m in selected)
    if not selected or need > RANGE_SHARE * total:
        _log(run_id, f"The analysis needs {limits.human(need)} of the {limits.human(total)} archive, so it is downloaded whole")
        return None
    archive_mod.check_budget(selected)
    _stage(run_id, "extracting", f"Reading {len(selected):,} of {len(members):,} files from the remote archive with HTTP ranges "
                                 f"({limits.human(need)} of {limits.human(total)}{', directory from cache' if meta else ''})")

    def prog(i: int, n: int, fetched: int, declared: int) -> None:
        _progress(run_id, "extracting", i, n, "files", bytes=fetched, bytes_total=declared)

    t1 = time.monotonic()
    got = archive_mod.fetch_members(url, total, [m["name"] for m in selected], RUNS_DIR / run_id / "x", auth=auth, cache_key=ckey,
                                    progress=prog, cancel=lambda: _check_cancel(run_id), deadline=deadline, rz=rz, listing=listing)
    timings["range_fetch_ms"] = _ms(t1)
    fetched = got["bytes_fetched"] + (0 if meta else listing.get("bytes_fetched", 0))
    _log(run_id, f"Received {limits.human(fetched)} in {got['requests'] + (0 if meta else listing.get('requests', 0))} ranged requests"
                 + (f"; {got['cached']} member(s) from cache" if got["cached"] else ""))
    return {"paths": got["paths"], "bytes_fetched": fetched, "requests": got["requests"], "archive_bytes": total, "listing": listing, "plan": pl,
            "selected": selected}


def archive_mod_cached_listing(ckey: str | None) -> dict | None:
    return cache_mod.read_meta(ckey).get("listing") if ckey else None


def _scope(report: dict, rec: dict, fetch: dict | None, params: dict) -> dict:
    """What a report covers, in words: Sample, Full dataset, Full selected date range/worksheet/file, Inspection only."""
    if report.get("kind") == "inspection":
        return {"kind": "inspection", "label": "Inspection only"}
    if report.get("coverage") != "full":
        return {"kind": "sample", "label": "Sample"}
    if params.get("dateFrom") or params.get("dateTo"):
        return {"kind": "date_range", "label": "Full selected date range"}
    ws = report.get("worksheet")
    if ws:
        return {"kind": "worksheet", "label": "Full selected worksheet", "file": ws["file"], "sheet": ws["sheet"], "sheets": ws["sheets"]}
    arc = report.get("archive") or {}
    if arc:
        data_like = [m for m in arc.get("candidates", []) if m["type"] in registry.TABULAR + registry.CONVERTED + ("sinex", "sinex-gz", "sinex-z")]
        if report.get("kind") in ("table", "trajectory", "sinex") and len(data_like) > len(arc.get("selected", [])):
            return {"kind": "file", "label": "Full selected file", "file": report.get("analyzed_file") or arc.get("selected", [None])[0]}
    if params.get("pairUrl"):
        return {"kind": "file", "label": "Full selected files", "file": report.get("analyzed_file")}
    if not fetch:
        return {"kind": "upload", "label": "Full uploaded file", "file": report.get("analyzed_file")}
    try:
        from .resolve import resolve

        listed = [f for f in resolve(rec)["files"] if f["supported"] and f.get("group") != "whole"]
    except Exception:  # noqa: BLE001
        listed = []
    if len(listed) > 1 and fetch.get("group") != "whole":
        return {"kind": "file", "label": "Full selected file", "file": fetch.get("name")}
    return {"kind": "dataset", "label": "Full dataset"}


def _execute(run_id: str, rec: dict, fetch: dict | None, local: Path | None, mode: str = "full", budget: float | None = None) -> None:
    folder = RUNS_DIR / run_id
    quick = mode == "sample"
    known_total, partial, method, plan, url = None, False, None, {}, None
    timings: dict = dict((fetch or {}).get("_timings") or {})
    remote, sha, cache_state, transferred, info = None, None, "none", 0, None
    try:
        folder.mkdir(parents=True, exist_ok=True)
        run0 = get(run_id, user=ANY) or {}
        params = run0.get("params") or {}
        prepare = quick and bool(params.get("prepare"))  # "Prepare archive and run sample": whole download, sampled analysis
        deadline = time.monotonic() + (QUICK_DEADLINE_S if quick and not prepare else FULL_DEADLINE_S)
        if budget:  # running inside the web app: stop cleanly before the platform kills the function
            deadline = min(deadline, time.monotonic() + budget)
        _update(run_id, status="running")
        if fetch:
            name = re.sub(r"[^A-Za-z0-9._-]+", "_", (fetch.get("name") or fetch["url"].rsplit("/", 1)[-1]).replace("/", "_"))[-120:] or "download"
            if not _ext_format(name) and registry.type_from_name(name) == "unknown":
                name += f".{fetch.get('format') or 'csv'}"
            path = folder / name
            auth = _auth_for(run0, fetch["url"])
            plan = plan_fetch(fetch, mode, params) if not fetch.get("blob") else {"url": fetch["url"], "count_url": None, "stop": None, "method": None}
            if prepare:
                plan = {**plan, "stop": None}
            url, stop, method = plan["url"], plan["stop"], plan["method"]
            if plan["count_url"]:
                known_total = _socrata_count(plan, timeout=max(0.1, min(10, deadline - time.monotonic())))
            label = "archive for a prepared sample" if prepare else "sample" if quick else "file"
            _stage(run_id, "downloading", f"Fetching {label}: {url}")

            def progress(done: int, total: int | None) -> None:
                _update(run_id, progress={"phase": "downloading", "done": done, "total_items": total, "unit": "bytes", "bytes": done, "total": total})
                _check_cancel(run_id)

            if plan.get("paged"):
                t0 = time.monotonic()
                fetched = _download_socrata(run_id, plan, path, known_total, deadline)
                timings["download_ms"] = _ms(t0)
                transferred = path.stat().st_size
                _log(run_id, f"Fetched all {fetched:,} rows in {max(1, -(-fetched // SODA_PAGE_ROWS)):,} ordered pages; the source count matches")
            elif stop:  # a streamed CSV/JSON sample: a partial read, never cached
                t0 = time.monotonic()
                got = fetch_mod.download(url, path, max_bytes=QUICK_MAX_BYTES, deadline=deadline, idle=IDLE_S, stop_after_lines=stop,
                                         progress=progress, auth=auth, retries=limits.DOWNLOAD_RETRIES, limit_name="quick_sample")
                timings["download_ms"] = _ms(t0)
                transferred = got["bytes"]
                partial = got["truncated"]
                if partial and not method:
                    method = f"first {QUICK_ROWS:,} rows of the file (download stopped early)"
                _log(run_id, f"Downloaded {limits.human(got['bytes'])}{' (stopped after the sample rows)' if partial else ''}")
            else:
                info = fetch.get("_probe") or {}
                if not info and not fetch.get("blob"):
                    t0 = time.monotonic()
                    info = fetch_mod.probe(url, None, auth=auth)
                    timings["probe_ms"] = _ms(t0)
                ckey = None if fetch.get("blob") else cache_mod.key(url, info, version=rec.get("sourceUpdatedAt"), user=run0.get("owner") if auth else None)
                hit = cache_mod.get_file(ckey)
                remote = None if hit else _remote_members(run_id, url, info, ckey, auth, quick=quick, params=params, deadline=deadline, timings=timings)
                if hit:
                    cache_mod.link_into(hit, path)
                    meta = cache_mod.read_meta(ckey)
                    transferred, cache_state = 0, "hit"
                    _log(run_id, f"Reused the cached download ({limits.human(hit.stat().st_size)}, same {cache_mod.validator(info).split(':')[0]} "
                                 f"as the source): nothing transferred")
                    sha = meta.get("sha256")
                elif remote:
                    transferred = remote["bytes_fetched"]
                    cache_state = "range" if transferred else "hit"
                else:
                    # Only line-based text can be cut after the sample rows; anything binary (archives, Excel, NetCDF...) is read whole.
                    whole = not quick or prepare or detected_kind(info) not in ("csv", "tsv", "json", "text", "sinex", "xml")
                    total_txt = f" ({limits.human(info.get('bytes_total'))})" if info.get("bytes_total") else ""
                    if detected_kind(info) == "zip" and info.get("bytes_total") and not info.get("ranges"):
                        _log(run_id, f"The server doesn't allow partial reads, so the whole archive{total_txt} is streamed once and cached "
                                     "for Look inside, samples and reruns")
                    t0 = time.monotonic()
                    got = fetch_mod.download(url, path, max_bytes=MAX_BYTES if whole else QUICK_MAX_BYTES, deadline=deadline, idle=IDLE_S,
                                             progress=progress, auth=auth, retries=limits.DOWNLOAD_RETRIES,
                                             limit_name="transfer" if whole else "quick_sample")
                    timings["download_ms"] = _ms(t0)
                    transferred, cache_state = got["bytes"], "miss"
                    _log(run_id, f"Downloaded {limits.human(got['bytes'])} in {timings['download_ms'] / 1000:.1f} s")
                    sha = _sha256(path)
                    cache_mod.put_file(ckey, path, {"url": url, "validator": cache_mod.validator(info), "sha256": sha})
            pair = params.get("pairUrl")
            if pair:
                pf = _pair_file(rec, fetch, pair)
                ppath = folder / ("pair_" + re.sub(r"[^A-Za-z0-9._-]+", "_", pf["name"].rsplit("/", 1)[-1]))
                got = fetch_mod.download(pf["url"], ppath, max_bytes=MAX_BYTES, deadline=deadline, idle=IDLE_S, auth=_auth_for(run0, pf["url"]),
                                         retries=limits.DOWNLOAD_RETRIES)
                transferred += got["bytes"]
                _log(run_id, f"Downloaded paired file {pf['name']}")
                params = {**params, "_pair_path": str(ppath)}
        else:
            path = folder / local.name
            shutil.move(str(local), path)
            if local.parent.parent == config.STATE_DIR and local.parent.name.startswith("tmp"):
                shutil.rmtree(local.parent, ignore_errors=True)
            transferred = path.stat().st_size
            _log(run_id, f"Received upload {path.name} ({limits.human(path.stat().st_size)})")
        _check_cancel(run_id)
        if remote:
            main = next(iter(remote["paths"].values()))
            detected = "zip"
            _update(run_id, file_format="zip", file_bytes=transferred, file_sha256=_sha256(main))
        else:
            sha = sha or _sha256(path)
            detected = registry.sniff_path(path)
            _update(run_id, file_format=detected, file_bytes=path.stat().st_size, file_sha256=sha)
        report = _run_handler(run_id, path, detected, folder, quick=quick, params=params, deadline=deadline,
                              known_total=known_total, partial=partial, method=method, remote=remote, timings=timings)
        report["transferred_bytes"] = transferred
        report["source_bytes"] = ((remote or {}).get("archive_bytes") or (path.stat().st_size if path.exists() else None)
                                  or (info or {}).get("bytes_total") or (transferred if cache_state == "miss" else None))
        report["detected_type"] = detected
        report["fetch"] = {"cache": cache_state, "transferred_bytes": transferred, "source_bytes": report["source_bytes"],
                           "requests": (remote or {}).get("requests")}
        if fetch and plan.get("paged"):
            if report["rows_analyzed"] != known_total or report["rows_skipped"]:
                raise FetchError(f"Profiled {report['rows_analyzed']:,} of {known_total:,} fetched rows ({report['rows_skipped']:,} unreadable). "
                                 "No full report was published.", "format")
            report["paged_source"] = True
            report["rows_fetched"] = known_total
            _log(run_id, f"Verified: {report['rows_analyzed']:,} rows profiled = {known_total:,} rows in the source")
        if fetch and not fetch.get("blob"):
            report["source_url"] = url
            report["params"] = {k: v for k, v in params.items() if v and not k.startswith("_")}
        if report.get("kind") == "inspection":
            _log(run_id, f"Inspection only: {report['inspection']['detected']} ({report['inspection']['file_count']:,} files). {report['inspection']['next']}")
        else:
            total_txt = f"{report['rows_total']:,}" if report.get("rows_total") is not None else "an unknown number of"
            unit = {"images": "images", "sinex": "station solutions"}.get(report.get("kind"), "rows")
            _log(run_id, f"Analyzed {report['rows_analyzed']:,} of {total_txt} {unit} ({report['coverage']}), {len(report['columns'])} columns")
        _check_cancel(run_id)
        _stage(run_id, "saving")
        _progress(run_id, "saving", 0, 1, "steps")
        t_save = time.monotonic()
        report["scope"] = _scope(report, rec, fetch, params)
        report["timings"] = timings
        finished = _now()
        _update(run_id, finished_at=finished, report=report, summary=_summary(run_id, report))
        run = get(run_id, user=ANY)
        # Save the curated record and verified facts first, then flip to "succeeded", so anyone who sees the
        # finished run also sees the dataset in Curated Packs (same id, upserted: retries never duplicate it).
        store.save_curated_record(rec)
        if report.get("columns") and not run.get("owner"):
            store.set_overlay(rec["id"], _overlay(run, report))
        _update(run_id, status="succeeded", stage="done")
        timings["save_ms"] = _ms(t_save)
        report["timings"] = timings
        _update(run_id, report=report)
        _log(run_id, "Timings: " + ", ".join(f"{k.removesuffix('_ms')} {v / 1000:.2f} s" for k, v in timings.items() if k.endswith("_ms"))
             + f"; {limits.human(transferred)} transferred ({cache_state})")
        _progress(run_id, "saving", 1, 1, "steps")
        _log(run_id, "Saved. The dataset now appears in Curated Packs as Analyzed.")
        if fetch and fetch.get("blob"):
            from .. import blob

            blob.delete(fetch["url"])
            _update(run_id, file_url=None)  # the upload was temporary; the report keeps the SHA-256
    except Exception as exc:  # never leave a run stuck in 'running'; the last successful report stays the latest
        kind = getattr(exc, "kind", None) or ("format" if isinstance(exc, ImportError_) else "error")
        msg = str(exc) if isinstance(exc, ImportError_) else f"{type(exc).__name__}: {exc}"
        stage = (get(run_id, user=ANY) or {}).get("stage") or "resolving"
        _log(run_id, f"Failed while {stage}: {msg}")
        _update(run_id, status="failed", finished_at=_now(), error=msg, error_kind=kind, error_detail=getattr(exc, "detail", None))
    finally:
        if fetch:  # downloads are re-fetchable; keep disk use bounded. Uploads stay for the notebook.
            shutil.rmtree(folder, ignore_errors=True)
        else:
            shutil.rmtree(folder / "x", ignore_errors=True)  # expanded archive members are rebuilt on demand


def _run_handler(run_id: str, path: Path, detected: str, folder: Path, *, quick: bool, params: dict, deadline: float,
                 known_total: int | None, partial: bool, method: str | None, remote: dict | None = None, timings: dict | None = None) -> dict:
    """Detect -> (inspect and extract archives) -> pick a handler from the registry -> analyze."""
    timings = timings if timings is not None else {}
    t_extract = time.monotonic()
    _stage(run_id, "extracting")
    claimed = registry.type_from_name(path.name)
    if remote:
        pass
    elif claimed in ("parquet", "zip", "xlsx") and detected not in {"xlsx": ("xlsx", "zip"), "zip": ("zip", "xlsx", "ods")}.get(claimed, (claimed,)):
        raise FetchError(f"{path.name} is named .{claimed} but its content is {detected} (no {claimed.upper()} signature). "
                         "The file is damaged or mislabelled.", "format")
    members: list[dict] = []
    archive_info = None
    work = folder / "x"
    if not remote and detected == "rar":
        raise FetchError("RAR archives can't be opened here. Extract it on your computer and upload the data files, or a ZIP of them.", "format",
                         limits.detail("format", None, actions=["upload"], format="rar"))
    if not remote and detected in ("tar", "7z"):
        _log(run_id, f"Expanding the {'tar' if detected == 'tar' else '7-Zip'} archive")
        path = archive_mod.repack(path, detected, folder / "r", deadline=deadline, cancel=lambda: _check_cancel(run_id),
                                  log=lambda line: _log(run_id, line))
        detected = "zip"
    if remote:
        listing, pl = remote["listing"], remote["plan"]
        members, handler, selected = listing["members"], pl["handler"], remote["selected"]
        paths, root = list(remote["paths"].values()), work
        archive_info = {"name": path.name, "transferred_bytes": remote["bytes_fetched"], "members_total": len(members),
                        "expanded_bytes": listing["expanded_bytes"], "extracted_files": len(paths), "extracted_bytes": sum(m["size"] for m in selected),
                        "skipped": listing["skipped"][:20], "scores": pl["scores"], "candidates": _candidates(members),
                        "selected": [m["name"] for m in selected][:50], "range_read": True, "archive_bytes": remote["archive_bytes"]}
        _log(run_id, f"ZIP lists {len(members):,} files ({limits.human(listing['expanded_bytes'])} expanded). {handler.label}: read "
                     f"{len(selected):,} file(s), {limits.human(archive_info['extracted_bytes'])}")
    elif detected == "zip":
        _log(run_id, "Inspecting the archive")
        listing = archive_mod.inspect_path(path)
        members = listing["members"]
        if archive_mod.has_inner_archives(members) and registry.plan(members, sample=quick, params=params)["handler"].key == "inspect":
            _log(run_id, "The data is inside archives within the archive: expanding them")
            path = archive_mod.repack(path, "zip", folder / "r", deadline=deadline, cancel=lambda: _check_cancel(run_id),
                                      log=lambda line: _log(run_id, line))
            listing = archive_mod.inspect_path(path)
            members = listing["members"]
        for sk in listing["skipped"][:5]:
            _log(run_id, f"Skipped {sk['name']}: {sk['reason']}")
        pl = registry.plan(members, sample=quick, params=params)
        handler, selected = pl["handler"], pl["selected"]
        need = archive_mod.check_budget(selected)
        _log(run_id, f"ZIP lists {len(members):,} files ({limits.human(listing['expanded_bytes'])} expanded). "
                     f"{handler.label}: extracting {len(selected):,} file(s), {limits.human(need)}")

        def xprog(i: int, n: int, written: int, declared: int) -> None:
            _progress(run_id, "extracting", i, n, "files", bytes=written, bytes_total=declared)

        files = archive_mod.extract(path, [m["name"] for m in selected], work, progress=xprog, cancel=lambda: _check_cancel(run_id),
                                    deadline=deadline)
        paths = list(files.values())
        archive_info = {"name": path.name, "transferred_bytes": path.stat().st_size, "members_total": len(members),
                        "expanded_bytes": listing["expanded_bytes"], "extracted_files": len(paths), "extracted_bytes": need,
                        "skipped": listing["skipped"][:20], "scores": pl["scores"],
                        "candidates": _candidates(members), "selected": [m["name"] for m in selected][:50]}
        path.unlink(missing_ok=True)  # the expanded members are all the handler needs; free the disk
        root = work
    elif detected in ("gzip", "compress", "sinex-gz", "bzip2", "xz") and not path.name.lower().endswith((".csv.gz", ".tsv.gz", ".json.gz")):
        out = work / re.sub(r"\.(gz|z|bz2|xz)$", "", path.name, flags=re.I)
        work.mkdir(parents=True, exist_ok=True)
        _log(run_id, f"Decompressing {path.name}")
        archive_mod.decompress(path, out, kind={"compress": "compress", "bzip2": "bzip2", "xz": "xz"}.get(detected, "gzip"))
        inner = registry.sniff_path(out)
        members = [{"name": out.name, "size": out.stat().st_size, "type": inner}]
        pl = registry.plan(members, sample=quick, params=params)
        handler, paths, root = pl["handler"], [out] if pl["selected"] else [out], work
    else:
        t = "csv" if detected in ("gzip",) else detected
        named = registry.type_from_name(path.name)
        if named in registry.CONVERTED and t in ("binary", "text", "csv", "tsv", "unknown"):
            t = named  # Stata, SAS transport and similar files have no reliable signature: trust the extension
        if t == "xml":
            from .formats import convert

            if convert.is_xml_table(path):
                t = "xmltable"
                params = {**params, "_kind": "xmltable"}
        members = [{"name": path.name, "size": path.stat().st_size, "type": t}]
        pl = registry.plan(members, sample=quick, params=params)
        handler, paths, root = pl["handler"], [path], folder
    timings.setdefault("extract_ms", _ms(t_extract))
    _check_cancel(run_id)
    _stage(run_id, "profiling", f"Analyzing as {handler.label}")
    t_profile = time.monotonic()
    marks: dict = {}

    def charts_mark() -> None:
        marks["charts"] = time.monotonic()
        _stage(run_id, "charting")
    job = registry.Job(paths=paths, root=root, sample=quick, deadline=deadline, params=params, members=members if archive_info else [],
                       progress=lambda phase, done, total, unit: _progress(run_id, phase, done, total, unit),
                       cancel=lambda: _check_cancel(run_id), log=lambda line: _log(run_id, line),
                       on_charts=charts_mark, known_total=known_total, partial=partial, method=method,
                       extra={"row_limit": QUICK_ROWS if quick else None, "pair_path": Path(params["_pair_path"]) if params.get("_pair_path") else None})
    try:
        report = handler.analyze(job)
    except FetchError as exc:
        # A scientific file whose layout can't be tabulated still gets a useful report: what it is and why it wasn't analyzed.
        if handler.key != "tabular" or exc.kind not in ("format", "not_data") or not any(m["type"] in ("netcdf", "hdf5") for m in members):
            raise
        _log(run_id, f"Couldn't tabulate: {exc}. Showing an inspection instead.")
        handler = registry.get("inspect")
        job.extra["fallback_reason"] = str(exc)
        report = handler.analyze(job)
    end = time.monotonic()
    timings["profile_ms"] = int(((marks.get("charts") or end) - t_profile) * 1000)
    timings["charts_ms"] = int((end - marks["charts"]) * 1000) if marks.get("charts") else 0
    report["handler"] = handler.key
    report["handler_label"] = handler.label
    report.setdefault("kind", "table")
    if archive_info:
        report["archive"] = archive_info
        if len(selected) == 1 and report.get("kind") in ("table", "trajectory"):
            report["analyzed_file"] = selected[0]["name"] if not report.get("worksheet") else report["analyzed_file"]
    return report


def _candidates(members: list[dict]) -> list[dict]:
    """What the member picker shows: data-like files first, biggest first, capped."""
    order = {t: i for i, t in enumerate(("csv", "tsv", "parquet", "json", "xlsx", "sinex", "sinex-gz", "sinex-z"))}
    data = sorted(members, key=lambda m: (order.get(m["type"], 50), -m["size"]))
    return data[:300]


def _pair_file(rec: dict, fetch: dict, pair_url: str) -> dict:
    """A paired file must be one the provider listed for this dataset (never an arbitrary URL)."""
    from .resolve import find

    f = find(rec, pair_url)
    if not f:
        raise FetchError("The paired metadata file isn't listed for this dataset.", "not_found")
    return f


INLINE = os.getenv("DSP_ANALYSIS_INLINE", "0") == "1"
# queue: the API only records the job; app.worker (Docker service, or any machine with disk and time) runs it.
RUN_MODE = config.RUN_MODE


def _launch(run_id: str, rec: dict, fetch: dict | None, local: Path | None, mode: str = "full") -> None:
    if RUN_MODE == "queue" and local is None:
        _update(run_id, job={"rec": rec, "fetch": fetch, "mode": mode})
        _log(run_id, "Queued for the analysis worker")
        return
    if INLINE or (RUN_MODE == "queue" and local is not None):
        # A file uploaded straight to this instance exists only here (no shared disk on Vercel), and a background thread is
        # frozen once the response is sent: analyze it within this request. Vercel caps such uploads at 4.5 MB, so it's quick.
        _execute(run_id, rec, fetch, local, mode, **({"budget": config.INLINE_BUDGET_SECONDS} if RUN_MODE == "queue" else {}))
    else:
        threading.Thread(target=_execute, args=(run_id, rec, fetch, local, mode), daemon=True, name=f"analysis-{run_id}").start()


def claim(run_id: str, worker: str) -> dict | None:
    """Take this one queued job (atomic: a second caller gets None)."""
    if durable.execute_count("update analysis_runs set status='running', worker=?, stage='resolving' where id=? and status='queued' "
                             "and job is not null", (worker, run_id)):
        return get(run_id, user=ANY)
    return None


def claim_next(worker: str) -> dict | None:
    """Worker side of queue mode: atomically take the oldest queued job."""
    for row in durable.query("select id from analysis_runs where status='queued' and job is not null order by created_at limit 5"):
        if durable.execute_count("update analysis_runs set status='running', worker=?, stage='resolving' where id=? and status='queued'", (worker, row["id"])):
            return get(row["id"], user=ANY)
    return None


def _pick(rec: dict, url: str | None, index: int | None, user: str | None = None) -> dict:
    from .resolve import find, resolve

    if url:
        f = find(rec, url, user=user)
    else:
        files = resolve(rec, user=user)["files"]
        f = files[index] if index is not None and 0 <= index < len(files) else None
    if not f:
        raise FetchError("That file isn't listed for this dataset any more. Refresh the file list and choose again.", "not_found")
    if not f["supported"]:
        raise FetchError(f"{f['name']} is {f['format'].upper()}, which has no analyzer yet. Upload a CSV, Parquet, JSON, Excel, SINEX, "
                         "image archive or ZIP instead, or run an inspection.", "format",
                         limits.detail("format", None, actions=["open_source", "upload"], format=f["format"]))
    return f


def preflight(f: dict, mode: str, params: dict | None = None, auth: dict | None = None, rec: dict | None = None, user: str | None = None) -> dict:
    """Check the actual file before a job exists: access, content type, archive type and size for the chosen mode."""
    params = params or {}
    plan = plan_fetch(f, mode, params)
    probe_url = (_with_where(f["sample_url"].replace("{n}", "1"), _socrata_where(f, params))
                 if f.get("sample_url") and (mode == "sample" or plan.get("paged")) else plan["url"])
    info = fetch_mod.probe(probe_url, f.get("format") if f.get("format") in ("csv", "tsv", "json", "parquet") else None, auth=auth)
    if plan.get("paged"):
        rows = _socrata_count(plan, timeout=10)
        if rows is None:
            raise FetchError("The source didn't return a row count, so a complete full run can't be verified. Retry later, or run a sample.",
                             "network")
        info["row_total"] = rows
    total = info["bytes_total"] or f.get("bytes")
    whole = mode == "full" or params.get("prepare")
    streamable = mode == "sample" and (f.get("sample_url") or (info.get("detected") in ("csv", "tsv", "json") and info["kind"] == "text"))
    # A ZIP whose server honours byte ranges, or one already in the cache, needs no whole download for a sample.
    cached = bool(cache_mod.get_file(cache_mod.key(f["url"], info, version=(rec or {}).get("sourceUpdatedAt"), user=user if auth else None)))
    ranged = info.get("detected") == "zip" and info.get("ranges")
    info["cached"] = cached
    if not whole and not streamable and total and total > QUICK_MAX_BYTES and not (ranged or cached):
        what = "archive" if info.get("detected") == "zip" else info.get("detected") or f.get("format")
        actions = (["prepare_archive_sample", "full"] if total <= MAX_BYTES else ["open_source"])
        raise FetchError(f"{f['name']} is {limits.human(total)} and has to be read whole ({what}), more than a Quick sample downloads "
                         f"({limits.human(QUICK_MAX_BYTES)}). Prepare the archive and run a sample on it, or run a full analysis.", "too_large",
                         limits.detail("quick_sample", total, estimated=not info["bytes_total"], actions=actions, detected=what,
                                       limit_value=QUICK_MAX_BYTES))
    if whole and not plan.get("paged") and total and total > MAX_BYTES:
        raise FetchError(f"{f['name']} is {limits.human(total)}, over the {limits.human(MAX_BYTES)} transfer limit (DSP_MAX_TRANSFER_BYTES). "
                         "Nothing was downloaded.", "too_large",
                         limits.detail("transfer", total, estimated=not info["bytes_total"], limit_value=MAX_BYTES,
                                       actions=(["run_sample"] if streamable or f.get("sample_url") else []) + ["open_source"]))
    return info


def start_from_file(rec: dict, url: str | None = None, index: int | None = None, mode: str = "sample", params: dict | None = None,
                    user: str | None = None) -> str:
    """Analyze one of the dataset's resolved files. mode="sample" (default): the first rows only, within a
    60-second budget (params.prepare: download the whole archive first, then sample it). mode="full": everything
    within the transfer and extraction budgets and DSP_FULL_DEADLINE_SECONDS.
    params: {dateField, dateFrom, dateTo} (Socrata), {members, handler} (archives), {pairUrl} (paired files)."""
    t0 = time.monotonic()
    f = _pick(rec, url, index, user)
    discovery_ms = _ms(t0)
    params = {k: v for k, v in (params or {}).items() if v}
    auth = None
    from .. import kaggle_connect

    if user and kaggle_connect.is_kaggle_url(f["url"]):
        auth = kaggle_connect.auth_headers(user)
    t1 = time.monotonic()
    info = preflight(f, mode, params, auth=auth, rec=rec, user=user)  # raises before a run exists: no "Analyzing" for a file that can't run
    timings = {"discovery_ms": discovery_ms, "preflight_ms": _ms(t1)}
    run_id = _create(rec, f.get("name") or f["url"].rsplit("/", 1)[-1], f["url"], mode, params, owner=user)
    probe = {k: info.get(k) for k in ("bytes_total", "etag", "last_modified", "ranges", "detected", "kind")} if not f.get("sample_url") else None
    _launch(run_id, rec, {**f, "_probe": probe, "_timings": timings}, None, mode)
    return run_id


def retry(run_id: str, mode: str | None = None, user: str | None = None, params: dict | None = None) -> str:
    """Run the same file again (optionally switching sample/full or changing params). Uploads have to be uploaded again."""
    run = get(run_id, user=user)
    if not run:
        raise FetchError("Analysis not found.", "not_found")
    if not run.get("file_url"):
        raise FetchError("This analysis used an uploaded file, which isn't kept. Upload the file again.", "not_found")
    rec = store.get_record(run["dataset_id"])
    if not rec:
        raise FetchError("The dataset is no longer in the catalog.", "not_found")
    merged = {**(run.get("params") or {}), **(params or {})}
    return start_from_file(rec, url=run["file_url"], mode=mode or run.get("mode") or "sample", params=merged, user=user)


def start_from_listed_file(rec: dict, index: int, background: bool = True) -> str:  # kept for older clients
    return start_from_file(rec, index=index)


def start_from_upload(rec: dict, path: Path, background: bool = True, user: str | None = None) -> str:
    run_id = _create(rec, path.name, None, "full", owner=user)
    _launch(run_id, rec, None, path)
    return run_id


def start_from_blob(rec: dict, url: str, name: str, user: str | None = None) -> str:
    """A file the browser uploaded straight to Vercel Blob (private, multipart for large files)."""
    from .. import blob

    if not blob.is_blob_url(url) or "/uploads/" not in url.split("?")[0]:
        raise ImportError_("Only files uploaded to this app's Blob store can be analyzed this way.")
    try:  # a definite answer now beats a failed run later (token mismatch, upload that never finished, too large)
        size = blob.probe(url)
    except blob.BlobProblem as exc:
        raise FetchError(str(exc), exc.kind) from exc
    if size and size > MAX_BYTES:
        raise FetchError(f"{Path(name).name} is {limits.human(size)}, over the {limits.human(MAX_BYTES)} transfer limit (DSP_MAX_TRANSFER_BYTES).",
                         "too_large", limits.detail("transfer", size, limit_value=MAX_BYTES, actions=["open_source"]))
    run_id = _create(rec, Path(name).name, None, "full", owner=user)
    _launch(run_id, rec, {"url": url, "name": Path(name).name, "blob": True}, None)
    return run_id


def recover_interrupted() -> None:
    """At startup. With a shared Postgres other instances may be mid-run, so only expire stale runs there."""
    if durable.IS_POSTGRES or RUN_MODE == "queue":
        _expire_stale()
    else:
        durable.execute("update analysis_runs set status='failed', finished_at=?, error=? where status in ('queued','running')",
                        (_now(), "Interrupted: the server restarted during this analysis. Run it again."))


def notebook(run_id: str) -> bytes:
    import nbformat as nbf

    run = get(run_id)
    if not run or run["status"] != "succeeded":
        raise FileNotFoundError(run_id)
    folder = RUNS_DIR / run_id
    data = next((p for p in folder.iterdir() if _ext_format(p.name) in ("csv", "tsv", "parquet", "json")), None) if folder.exists() else None
    rep = run["report"] or {}
    path = (data.resolve().as_posix() if data else None) or rep.get("source_url") or run.get("file_url") or (folder / run["file_name"]).as_posix()
    read = {"parquet": f"pd.read_parquet(r'{path}')", "json": f"pd.read_json(r'{path}', lines=True)",
            "tsv": f"pd.read_csv(r'{path}', sep='\\t')"}.get(run["file_format"], f"pd.read_csv(r'{path}')")
    if rep.get("paged_source") and not data:
        read = (f"pd.concat([pd.read_csv({path!r} + f'&$limit={{min({SODA_PAGE_ROWS}, {rep['rows_analyzed']} - offset)}}&$offset={{offset}}') "
                f"for offset in range(0, {rep['rows_analyzed']}, {SODA_PAGE_ROWS})], ignore_index=True)"
                if rep["rows_analyzed"] else f"pd.read_csv({path!r} + '&$limit=1').iloc[:0]")
    if run.get("mode") == "sample" and rep.get("rows_analyzed") and "$limit" not in path and read.startswith("pd.read_csv"):
        read = read[:-1] + f", nrows={rep['rows_analyzed']})"  # same rows as the report, not the whole export
    src = run["source"] or {}
    nb = nbf.v4.new_notebook()
    nb.cells = [
        nbf.v4.new_markdown_cell(f"# {src.get('title', run['dataset_id'])}\nFile `{run['file_name']}` analyzed {run['finished_at'][:10]}. "
                                 f"Source: {src.get('canonicalUrl')}. License: {src.get('license') or 'unknown'} - check it before publishing."),
        nbf.v4.new_code_cell(f"import pandas as pd\ndf = {read}\nprint(df.shape)\ndf.head()"),
        nbf.v4.new_code_cell("pd.DataFrame({'dtype': df.dtypes.astype(str), 'missing_pct': (df.isna().mean() * 100).round(2)})"),
        nbf.v4.new_code_cell("print('duplicate rows:', df.duplicated().sum())\ndf.describe(include='all').T"),
    ]
    return nbf.writes(nb).encode("utf-8")


def delete_files_for(run_id: str) -> None:
    shutil.rmtree(RUNS_DIR / run_id, ignore_errors=True)
