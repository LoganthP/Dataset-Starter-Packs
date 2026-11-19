"""Saved comparisons: an immutable snapshot of 2-3 datasets, the criteria used, and the exact
analysis-run ids at save time. Re-analyzing a dataset later never rewrites a saved comparison."""
from __future__ import annotations

import datetime as dt
import json
import urllib.parse
import uuid

from .. import durable
from . import analysis, search, store


def analysis_summary(run: dict | None) -> dict | None:
    if not run or run.get("status") != "succeeded":
        return None
    rep = run["report"] or {}
    return {"runId": run["id"], "at": run["finished_at"], "file": run["file_name"], "coverage": rep.get("coverage"),
            "sampleMethod": rep.get("sample_method"), "rowsTotal": rep.get("rows_total"), "rowsAnalyzed": rep.get("rows_analyzed"),
            "missingPct": rep.get("missing_pct"), "duplicateRows": rep.get("duplicate_rows"), "dateCoverage": rep.get("date_coverage"),
            "schema": [{"name": c["name"], "type": c["type"], "missingPct": c["missing_pct"]} for c in rep.get("columns", [])]}


def build(ids: list[str], criteria: str) -> list[dict]:
    """Current comparison data: dataset details evaluated against the criteria, plus each latest analysis."""
    params = dict(urllib.parse.parse_qsl(criteria))
    latest = analysis.latest_successful()
    out = []
    for rid in ids:
        d = search.detail(rid, params)
        if d is None:
            raise KeyError(rid)
        run = analysis.get(latest[rid]["runId"]) if rid in latest else None
        out.append({**d, "analysis": analysis_summary(run)})
    return out


def save(ids: list[str], criteria: str, name: str | None) -> dict:
    items = build(ids, criteria)
    rid = uuid.uuid4().hex[:12]
    created = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    run_ids = {i["id"]: (i["analysis"] or {}).get("runId") for i in items}
    title = name or " vs ".join(i["title"][:40] for i in items)
    durable.execute("insert into comparison_reports (id, name, created_at, dataset_ids, analysis_run_ids, criteria, snapshot) values (?,?,?,?,?,?,?)",
                    (rid, title, created, json.dumps(ids), json.dumps(run_ids), criteria, json.dumps(items)))
    return get(rid)


def _row(r) -> dict:
    d = dict(r)
    for k in ("dataset_ids", "analysis_run_ids", "snapshot"):
        d[k] = json.loads(d[k])
    return d


def get(report_id: str) -> dict | None:
    r = durable.one("select * from comparison_reports where id=?", (report_id,))
    return _row(r) if r else None


def list_reports(limit: int = 100) -> list[dict]:
    rows = durable.query("select id, name, created_at, dataset_ids, analysis_run_ids, criteria from comparison_reports order by created_at desc limit ?",
                         (limit,))
    titles = {k: v["title"] for k, v in store.all_records().items()}
    out = []
    for r in rows:
        d = dict(r)
        d["dataset_ids"] = json.loads(d["dataset_ids"])
        d["analysis_run_ids"] = json.loads(d["analysis_run_ids"])
        d["dataset_titles"] = [titles.get(i, i) for i in d["dataset_ids"]]
        out.append(d)
    return out


def delete(report_id: str) -> None:
    durable.execute("delete from comparison_reports where id=?", (report_id,))
