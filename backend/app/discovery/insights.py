"""Reusable insights for any analyzed table. Each block activates only when the fields it needs exist.

  time         a date/timestamp column  -> records per month (or year), and per hour of day when times exist
  categories   low-cardinality text      -> ranked counts, missing values kept as "Unknown"
  numbers      numeric measures          -> value counts (few distinct values) or a 12-bin histogram
  coordinates  a latitude/longitude pair -> share of rows with a valid pair, bounding box, points for a map
  findings     plain-language data-quality notes, including what a sample can and cannot support

Everything is computed on the analyzed rows (table `t`): the sample, or the full file.
"""
from __future__ import annotations

import re

KEYWORD_PLACE = re.compile(r"borough|district|state|region|city|county|ward|zone|country|province|neighbou?rhood", re.I)
KEYWORD_CATEGORY = re.compile(r"borough|state|region|district|city|county|ward|type|category|class|kind|status|condition|cause|factor|"
                              r"weather|severity|mode|gender|sex|species|genre|country|zone|light|surface", re.I)
KEYWORD_MEASURE = re.compile(r"voltage|power|energy|consumption|intensity|load|demand|injur|kill|fatal|death|casualt|victim|count|number|num_|"
                             r"speed|amount|price|cost|temp|precip|rain|humid|wind|pressure|level|flow|duration|distance|age|score|rating|"
                             r"weight|height|population|value|total", re.I)
# Which measures to chart first when several exist (household power: Voltage, then active power, ...).
PRIORITY = [re.compile(p) for p in (r"voltage", r"(^|_)active_power", r"consumption", r"energy", r"power", r"temp", r"precip", r"injur",
                                      r"kill", r"fatal", r"casualt", r"speed", r"intensity", r"load", r"demand", r"price", r"amount")]
USAGE = re.compile(r"(^|_)active_power|consumption|energy|load|demand|usage|kwh", re.I)
BUCKETS = [("1 minute", 60), ("5 minutes", 300), ("15 minutes", 900), ("1 hour", 3600), ("6 hours", 21600), ("1 day", 86400),
           ("7 days", 604800), ("1 month", 2_629_746), ("1 year", 31_556_952)]
SKIP_NUMERIC = re.compile(r"(^|_)(id|code|zip|postcode|postal|lat|latitude|lon|lng|long|longitude|x|y|year|fips|key)($|_)|_id$", re.I)
LAT = re.compile(r"^(lat|latitude|.*_lat|.*_latitude|y_coord.*)$", re.I)
LON = re.compile(r"^(lon|lng|long|longitude|.*_lon|.*_lng|.*_longitude|x_coord.*)$", re.I)


def q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _timestamp_expr(columns: list[dict]) -> tuple[str, str] | None:
    """(SQL expression, label) for the best timestamp: a TIMESTAMP column, or a DATE plus a separate TIME column."""
    dates = [c for c in columns if c["kind"] == "datetime" and c["type"] != "TIME"]
    if not dates:
        return None
    col = min(dates, key=lambda c: c["missing"])
    expr = q(col["name"]) if not col.get("parsed_as") else f"try_cast({q(col['name'])} as timestamp)"
    tcols = [c for c in columns if c["type"] == "TIME"]
    if col["type"] == "DATE" and tcols:
        return f"({q(col['name'])} + {q(tcols[0]['name'])})", f"{col['name']} + {tcols[0]['name']}"
    return f"cast({expr} as timestamp)", col["name"]


def _measures(columns: list[dict], exclude: set[str]) -> list[dict]:
    cands = [c for c in columns if c["kind"] == "numeric" and c["name"] not in exclude and not SKIP_NUMERIC.search(c["name"])
             and c.get("min") is not None and c["min"] != c.get("max")]
    def rank(c):
        n = c["name"].lower()
        hits = [i for i, k in enumerate(PRIORITY) if k.search(n)]
        return (min(hits) if hits else len(PRIORITY), not KEYWORD_MEASURE.search(c["name"]), c["missing_pct"])

    cands.sort(key=rank)
    return cands


def _trends(con, columns: list[dict], exclude: set[str]) -> dict | None:
    """Average of the main numeric measures over time (e.g. Voltage over time), and by hour of day."""
    ts = _timestamp_expr(columns)
    # Continuous measures only (decimals, or many distinct values); small integer counts are charted as distributions instead.
    measures = [c for c in _measures(columns, exclude) if KEYWORD_MEASURE.search(c["name"])
                and ((c["distinct"] or 0) > 12 or any(k in c["type"] for k in ("DOUBLE", "FLOAT", "DECIMAL", "REAL")))][:3]
    if not ts or not measures:
        return None
    expr, label = ts
    lo, hi = con.execute(f"select min({expr}), max({expr}) from t").fetchone()
    if lo is None or hi is None or hi <= lo:
        return None
    span = (hi - lo).total_seconds()
    bucket = next((b for b, sec in BUCKETS if span / sec <= 200), "1 year")
    series = []
    for m in measures:
        rows = con.execute(f"select time_bucket(interval '{bucket}', {expr}) b, avg({q(m['name'])}) from t "
                           f"where {expr} is not null and {q(m['name'])} is not null group by 1 order by 1").fetchall()
        if len(rows) >= 3:
            series.append({"column": m["name"], "points": [[str(b), round(float(v), 4)] for b, v in rows]})
    out = {"time": label, "bucket": bucket, "series": series} if series else None
    hours = con.execute(f"select count(distinct hour({expr})) from t where {expr} is not null").fetchone()[0]
    if out and hours >= 6:
        # "Hourly consumption" when a usage measure exists, otherwise the first charted measure.
        m = next((x["column"] for x in series if USAGE.search(x["column"])), series[0]["column"])
        rows = dict(con.execute(f"select hour({expr}), avg({q(m)}) from t where {expr} is not null and {q(m)} is not null group by 1").fetchall())
        out["by_hour"] = {"column": m, "values": [[h, None if h not in rows else round(float(rows[h]), 4)] for h in range(24)]}
    return out


def card_preview(ins: dict) -> dict | None:
    """The chart shown on a Curated Packs card: the most informative series the saved run has (>= 3 points)."""
    if not ins:
        return None
    tr = ins.get("trends") or {}
    if tr.get("series") and len(tr["series"][0]["points"]) >= 3:
        s = tr["series"][0]
        return {"label": f"{s['column']} over time (avg per {tr['bucket']})", "values": [v for _, v in s["points"]][-120:], "kind": "line"}
    t = ins.get("time") or {}
    if len(t.get("series") or []) >= 3:
        return {"label": f"Records per {t['grain']}", "values": [v for _, v in t["series"]][-60:], "kind": "bars"}
    if t.get("by_hour") and sum(1 for _, v in t["by_hour"] if v) >= 3:
        return {"label": "Records by hour of day", "values": [v for _, v in t["by_hour"]], "kind": "bars"}
    for c in ins.get("categories") or []:
        if len(c["values"]) >= 2:
            return {"label": f"Top {c['column']} values", "values": [v for _, v in c["values"]], "kind": "bars"}
    for m in ins.get("numbers") or []:
        vals = [v for *_, v in (m.get("bins") or m.get("values") or [])]
        if len(vals) >= 3:
            return {"label": f"{m['column']} distribution", "values": vals, "kind": "bars"}
    return None


def _time(con, columns: list[dict], n: int) -> dict | None:
    dates = [c for c in columns if c["kind"] == "datetime" and c["type"] != "TIME"]
    if not dates:
        return None
    col = min(dates, key=lambda c: c["missing"])
    expr = q(col["name"]) if not col.get("parsed_as") else f"try_cast({q(col['name'])} as timestamp)"
    span = con.execute(f"select date_diff('month', min({expr}), max({expr})) from t").fetchone()[0] or 0
    grain = "month" if span <= 120 else "year"
    fmt = "%Y-%m" if grain == "month" else "%Y"
    rows = con.execute(f"select strftime({expr}, '{fmt}') k, count(*) from t where {expr} is not null group by 1 order by 1").fetchall()
    out = {"column": col["name"], "grain": grain, "series": [[k, c] for k, c in rows], "missing": col["missing"]}
    moy = dict(con.execute(f"select month({expr}), count(*) from t where {expr} is not null group by 1").fetchall())
    out["by_month_of_year"] = [[m, moy.get(m, 0)] for m in range(1, 13)]
    # Hour of day: a separate TIME column (e.g. crash_time) or the timestamp itself when it carries times.
    tcols = [c for c in columns if c["type"] == "TIME"]
    hexpr = None
    if tcols:
        hexpr = f"hour({q(tcols[0]['name'])})"
        out["hour_column"] = tcols[0]["name"]
    elif "TIMESTAMP" in col["type"] or col.get("parsed_as"):  # a timestamp that carries times
        has_times = con.execute(f"select count(*) from t where {expr} is not null and cast({expr} as time) <> time '00:00:00'").fetchone()[0]
        if has_times > 0.2 * n:
            hexpr = f"hour({expr})"
            out["hour_column"] = col["name"]
    if hexpr:
        week_hour = con.execute(
            f"select isodow({expr}), {hexpr}, count(*) from t "
            f"where {expr} is not null and {hexpr} is not null group by 1,2 order by 1,2"
        ).fetchall()
        counts = dict(con.execute(f"select {hexpr} h, count(*) from t where {hexpr} is not null group by 1").fetchall())
        out["by_hour"] = [[h, counts.get(h, 0)] for h in range(24)]
        # A weekday-by-hour heatmap only says something for event records (crashes, calls, trips), whose counts vary
        # by hour. Regular readings (one row per minute) give a flat grid, so they don't get one.
        hourly = [v for _, v in out["by_hour"]]
        mean = sum(hourly) / 24
        spread = (sum((v - mean) ** 2 for v in hourly) / 24) ** 0.5 / mean if mean else 0
        if len({day for day, _, _ in week_hour}) >= 5 and len({hour for _, hour, _ in week_hour}) >= 6 and spread > 0.15:
            out["weekday_hour"] = [list(row) for row in week_hour]
    return out


def _categories(con, columns: list[dict], n: int, exclude: set[str]) -> list[dict]:
    cands = [c for c in columns if c["kind"] == "text" and 2 <= (c["distinct"] or 0) <= 60 and c["name"] not in exclude
             and c["missing_pct"] < 95]
    cands.sort(key=lambda c: (not KEYWORD_PLACE.search(c["name"]), not KEYWORD_CATEGORY.search(c["name"]), c["missing_pct"] > 60,
                              c["distinct"] > 25, c["missing_pct"]))
    out = []
    for c in cands[:3]:
        rows = con.execute(f"select {q(c['name'])}, count(*) from t where {q(c['name'])} is not null group by 1 order by 2 desc, 1 limit 11").fetchall()
        top = [[str(k), v] for k, v in rows[:10]]
        other = n - c["missing"] - sum(v for _, v in top)
        out.append({"column": c["name"], "values": top, "other": other, "unknown": c["missing"], "distinct": c["distinct"]})
    return out


def _numbers(con, columns: list[dict], exclude: set[str]) -> list[dict]:
    cands = _measures(columns, exclude)
    out = []
    for c in cands[:4]:
        name = q(c["name"])
        if (c["distinct"] or 0) <= 12:
            rows = con.execute(f"select {name}, count(*) from t where {name} is not null group by 1 order by 1").fetchall()
            out.append({"column": c["name"], "kind": "counts", "values": [[_num(k), v] for k, v in rows], "missing": c["missing"]})
        else:
            lo, hi = float(c["min"]), float(c["max"])
            width = (hi - lo) / 12
            rows = con.execute(f"select least(cast(floor(({name} - {lo}) / {width}) as integer), 11) b, count(*) from t "
                               f"where {name} is not null group by 1 order by 1").fetchall()
            counts = dict(rows)
            out.append({"column": c["name"], "kind": "histogram", "missing": c["missing"],
                        "bins": [[round(lo + i * width, 4), round(lo + (i + 1) * width, 4), counts.get(i, 0)] for i in range(12)]})
    return out


def _num(v):
    return int(v) if isinstance(v, float) and v.is_integer() else v


def _coordinates(con, columns: list[dict], n: int) -> dict | None:
    nums = [c for c in columns if c["kind"] == "numeric"]
    lat = next((c for c in nums if LAT.match(c["name"])), None)
    lon = next((c for c in nums if LON.match(c["name"])), None)
    if not lat or not lon:
        return None
    la, lo = q(lat["name"]), q(lon["name"])
    both, zero, out_of_range = con.execute(
        f"select count(*) filter (where {la} is not null and {lo} is not null), "
        f"count(*) filter (where {la} = 0 and {lo} = 0), "
        f"count(*) filter (where {la} is not null and {lo} is not null and (abs({la}) > 90 or abs({lo}) > 180)) from t").fetchone()
    valid_where = f"{la} is not null and {lo} is not null and abs({la}) <= 90 and abs({lo}) <= 180 and not ({la} = 0 and {lo} = 0)"
    valid = con.execute(f"select count(*) from t where {valid_where}").fetchone()[0]
    box = con.execute(f"select min({la}), max({la}), min({lo}), max({lo}) from t where {valid_where}").fetchone()
    pts = con.execute(f"select round({la}, 5), round({lo}, 5) from t where {valid_where} using sample 1000 rows (reservoir, 7)").fetchall()
    return {"lat": lat["name"], "lon": lon["name"], "rows": n, "both_present": both, "valid": valid, "zero_pairs": zero,
            "out_of_range": out_of_range, "missing_either": n - both, "valid_pct": round(100 * valid / n, 1) if n else 0.0,
            "bbox": None if box[0] is None else {"min_lat": box[0], "max_lat": box[1], "min_lon": box[2], "max_lon": box[3]},
            "points": [[a, b] for a, b in pts]}


def _injury_outcomes(con, columns: list[dict]) -> dict | None:
    """Traffic reports with explicit person totals can summarize observed crash outcomes."""
    fields = {c["name"].lower(): c["name"] for c in columns if c["kind"] == "numeric"}
    injured = fields.get("number_of_persons_injured")
    killed = fields.get("number_of_persons_killed")
    if not injured or not killed:
        return None
    inj, fat = q(injured), q(killed)
    counts = con.execute(
        f"select count(*) filter (where {fat} > 0), "
        f"count(*) filter (where {fat} = 0 and {inj} > 0), "
        f"count(*) filter (where {fat} = 0 and {inj} = 0) from t"
    ).fetchone()
    return {"injured_field": injured, "killed_field": killed,
            "counts": [["Fatal", counts[0]], ["Injury, no fatality", counts[1]],
                       ["No injury reported", counts[2]]]}


def _findings(report: dict, ins: dict) -> list[dict]:
    out = []
    n = report["rows_analyzed"]
    if report["coverage"] == "sample":
        how = report.get("sample_method") or "a sample"
        ordered = "first" in how
        out.append({"level": "warn" if ordered else "info", "text": (
            f"These numbers describe {n:,} real records ({how}), not the whole dataset. "
            + ("The rows are the first ones in source order, not a random draw, so time and place patterns may not represent the "
               "full table. Use Full analysis or a date-filtered run before comparing years or locating hotspots."
               if ordered else "Treat shares as estimates; rare categories may be missing."))})
    if c := ins.get("coordinates"):
        bad = c["rows"] - c["valid"]
        out.append({"level": "warn" if c["valid_pct"] < 90 else "info",
                    "text": f"{c['valid']:,} of {c['rows']:,} rows ({c['valid_pct']}%) have a usable latitude-longitude pair"
                            + (f"; {bad:,} are missing a coordinate, at 0,0 or out of range." if bad else ".")})
    sparse = [x for x in report["columns"] if x["missing_pct"] >= 50]
    if sparse:
        names = ", ".join(x["name"] for x in sparse[:6]) + (f" and {len(sparse) - 6} more" if len(sparse) > 6 else "")
        out.append({"level": "warn", "text": f"{len(sparse)} of {len(report['columns'])} columns are at least half empty: {names}."})
    const = [x["name"] for x in report["columns"] if x["distinct"] == 1 and x["missing"] < n]
    if const:
        out.append({"level": "info", "text": f"Single-value columns (no information in these rows): {', '.join(const[:6])}."})
    if rel := ins.get("relationships"):
        top = rel["items"][0]
        if rel["enough"]:
            out.append({"level": "info", "text": f"{rel['target']} is most strongly associated with {top['column']} (Pearson r = {top['pearson']:+.2f}"
                        + (f", Spearman ρ = {top['spearman']:+.2f}" if top.get("spearman") is not None else "") + f", n = {top['n']:,}). "
                        "These are associations in the analyzed rows, not causes."})
        else:
            out.append({"level": "warn", "text": f"Only {max(d['n'] for d in rel['items'])} rows pair {rel['target']} with other fields; "
                        f"associations need at least {rel['min_rows']}, so none are charted."})
    if report.get("rows_skipped"):
        out.append({"level": "warn", "text": f"{report['rows_skipped']:,} rows couldn't be parsed and were skipped."})
    if report.get("duplicate_rows"):
        out.append({"level": "warn", "text": f"{report['duplicate_rows']:,} rows are exact duplicates of another row."})
    elif report.get("duplicate_rows") == 0:
        out.append({"level": "info", "text": "No exact duplicate rows in the analyzed records (this doesn't prove a unique ID across the full source)."})
    return out


TARGET = re.compile(r"melt|melting|(^|_)t_?m($|_)|target|label|(^|_)y($|_)|price|yield|strength|hardness|efficiency|score|outcome|response|property", re.I)
ID_LIKE = re.compile(r"(^|_)(id|index|idx|row|seq|number|no)($|_)", re.I)
UNIT_IN_NAME = re.compile(r"[\(\[]\s*([^()\[\]]{1,16}?)\s*[\)\]]\s*$")
MIN_RELATIONSHIP_ROWS = 30
SCATTER_POINTS = 600


def unit_from_name(name: str) -> str | None:
    """A unit only when the column header states it, e.g. 'Tm (K)' or 'density [g/cm3]'. Never guessed."""
    m = UNIT_IN_NAME.search(name)
    return m.group(1) if m else None


def _target(columns: list[dict], exclude: set[str]) -> dict | None:
    """The numeric field a table seems to be about: named like a target (melting point, label, price...), else none."""
    nums = [c for c in columns if c["kind"] == "numeric" and c["name"] not in exclude and not ID_LIKE.search(c["name"])
            and (c["distinct"] or 0) > 5 and c["missing_pct"] < 50]
    named = [c for c in nums if TARGET.search(c["name"])]
    if named:
        best = sorted(named, key=lambda c: (c["missing_pct"], -(c["distinct"] or 0)))[0]
        return {"column": best["name"], "reason": "named like a target or property", "unit": unit_from_name(best["name"])}
    return None


def _relationships(con, columns: list[dict], target: dict, n: int, exclude: set[str]) -> dict | None:
    """Pearson and Spearman associations between the target and every other numeric field (pairwise complete rows)."""
    t = target["column"]
    feats = [c for c in columns if c["kind"] == "numeric" and c["name"] not in (t, *exclude) and not ID_LIKE.search(c["name"])
             and (c["distinct"] or 0) > 2]
    if not feats:
        return None
    items = []
    for c in feats[:80]:
        a, b = q(t), q(c["name"])
        m, pr, sr = con.execute(f"""
            with p as (select {a} x, {b} y from t where {a} is not null and {b} is not null),
                 r as (select rank() over (order by x) rx, rank() over (order by y) ry from p)
            select (select count(*) from p), (select corr(x, y) from p), (select corr(rx, ry) from r)""").fetchone()
        if m and pr is not None and pr == pr:
            items.append({"column": c["name"], "n": m, "pearson": round(float(pr), 4), "spearman": None if sr is None or sr != sr else round(float(sr), 4),
                          "unit": unit_from_name(c["name"])})
    if not items:
        return None
    items.sort(key=lambda d: -abs(d["pearson"]))
    enough = max(d["n"] for d in items) >= MIN_RELATIONSHIP_ROWS
    return {"target": t, "rows": n, "min_rows": MIN_RELATIONSHIP_ROWS, "enough": enough, "items": items[:12], "tested": len(items)}


def _scatter(con, x: str, y: str) -> dict:
    total = con.execute(f"select count(*) from t where {q(x)} is not null and {q(y)} is not null").fetchone()[0]
    step = max(1, -(-total // SCATTER_POINTS))
    rows = con.execute(f"select {q(x)}, {q(y)} from (select {q(x)}, {q(y)}, row_number() over () rn from t "
                       f"where {q(x)} is not null and {q(y)} is not null) where (rn - 1) % {step} = 0").fetchall()
    return {"x": x, "y": y, "points": [[_num(float(a)), _num(float(b))] for a, b in rows], "total": total, "shown": len(rows),
            "x_unit": unit_from_name(x), "y_unit": unit_from_name(y)}


def _seasonal(con, columns: list[dict], trends: dict | None) -> dict | None:
    """Average of the main measure per month of year, per year: a period comparison when the data spans 2+ years."""
    if not trends or not trends.get("series"):
        return None
    ts = _timestamp_expr(columns)
    if not ts:
        return None
    expr, _ = ts
    m = trends["series"][0]["column"]
    rows = con.execute(f"select year({expr}) y, month({expr}) mo, avg({q(m)}) from t where {expr} is not null and {q(m)} is not null "
                       "group by 1, 2 order by 1, 2").fetchall()
    years = sorted({r[0] for r in rows})
    if len(years) < 2:
        return None
    keep = years[-4:]  # the latest four years keep the chart readable
    return {"column": m, "years": keep, "series": [{"year": y, "values": [[mo, round(float(v), 4)] for yy, mo, v in rows if yy == y]} for y in keep]}


def compute(con, report: dict) -> dict:
    """con has table `t` (the analyzed rows); report is the profile built from it."""
    columns, n = report["columns"], report["rows_analyzed"]
    ins: dict = {"rows": n, "scope": report["coverage"]}
    if not n:
        ins["findings"] = []
        return ins
    if t := _time(con, columns, n):
        ins["time"] = t
    coords = _coordinates(con, columns, n)
    if coords:
        ins["coordinates"] = coords
    exclude = {coords["lat"], coords["lon"]} if coords else set()
    ins["categories"] = _categories(con, columns, n, exclude)
    ins["numbers"] = _numbers(con, columns, exclude)
    if outcomes := _injury_outcomes(con, columns):
        ins["injury_outcomes"] = outcomes
    if tr := _trends(con, columns, exclude):
        ins["trends"] = tr
        if seasonal := _seasonal(con, columns, tr):
            ins["seasonal"] = seasonal
    if target := _target(columns, exclude):
        ins["target"] = target
        rel = _relationships(con, columns, target, n, exclude)
        if rel:
            ins["relationships"] = rel
            if rel["enough"] and rel["items"]:
                ins["scatter"] = _scatter(con, rel["items"][0]["column"], target["column"])
        # the target's distribution first among the number charts
        tcol = next((c for c in columns if c["name"] == target["column"]), None)
        # then the fields most associated with it, so the feature charts follow the relationship ranking
        top = [it["column"] for it in (rel or {}).get("items", [])[:2]]
        have = {nn["column"] for nn in ins["numbers"]}
        extra = [c for c in columns if c["name"] in top and c["name"] not in have]
        if extra:
            ins["numbers"] = _numbers(con, extra, set()) + ins["numbers"]
        if tcol and not any(nn["column"] == tcol["name"] for nn in ins["numbers"]):
            ins["numbers"] = (_numbers(con, [tcol], set()) + ins["numbers"])[:6]
        else:
            ins["numbers"].sort(key=lambda nn: nn["column"] != target["column"])
    ins["findings"] = _findings(report, ins)
    ins["preview"] = card_preview(ins)
    return ins
