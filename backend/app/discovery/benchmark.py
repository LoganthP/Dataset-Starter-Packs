"""Run catalog/benchmark.json against the live index. Used by tests and scripts/search_benchmark.py."""
from __future__ import annotations

import json

from . import search, store
from .vocab import parse_query

BENCHMARK = store.CATALOG_DIR / "benchmark.json"


def params_for(q: str) -> dict:
    """What the frontend does: parse the query, then send criteria as explicit params."""
    c = parse_query(q)
    return {
        "q": q,
        "fields": ",".join(c.fields),
        "min_years": "" if c.min_years is None else str(c.min_years),
        "formats": ",".join(c.formats),
        "region": c.region or "",
        "granularity": c.granularity or "",
        "commercial": "1" if c.commercial else "",
        "purpose": ",".join(c.purposes),
        "difficulty": ",".join(c.difficulty),
        "offline": "1" if c.offline else "",
        "notebook": "1" if c.notebook else "",
        "include_failed": "1",
        "page_size": "50",
    }


def run() -> dict:
    cases = json.loads(BENCHMARK.read_text(encoding="utf-8"))["queries"]
    rows, hits, violations = [], 0, 0
    for case in cases:
        res = search.search(params_for(case["q"]))
        items = res["items"]
        shown = [i["id"] for i in items if i["fit"] != "does-not-meet"]
        group = {i["id"]: i["fit"] for i in items}
        top5 = shown[:5]
        hit = any(e in top5 for e in case["expect_top5"])
        hits += hit
        problems = []
        for rid in case.get("never_meets", []):
            if group.get(rid) == "meets":
                problems.append(f"{rid} appeared as a confirmed match")
        for rid, want in case.get("expect_group", {}).items():
            if group.get(rid, "absent") != want:
                problems.append(f"{rid} is {group.get(rid, 'absent')}, expected {want}")
        # Hard-filter integrity: a 'meets' item can never have an unmet required criterion.
        for i in items:
            if i["fit"] == "meets" and any(r["required"] and r["outcome"] != "met" for r in i["reasons"]):
                problems.append(f"{i['id']} marked meets with an unmet requirement")
        violations += len(problems)
        rows.append({"id": case["id"], "hit": hit, "top5": top5, "problems": problems})
    return {"cases": len(cases), "top5_hit_rate": round(hits / len(cases), 3), "violations": violations, "rows": rows}
