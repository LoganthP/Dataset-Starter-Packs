"""Evaluate a DatasetRecord against Criteria using stored evidence only.

Each criterion produces a reason with an outcome:
    met        - supported by verified or provider-reported evidence
    unverified - evidence is missing or ambiguous; the user has to check
    failed     - evidence says it does not satisfy the requirement
Required criteria decide the group: any failed -> does-not-meet; any unverified -> needs-verification;
otherwise meets. Preferred criteria (Criteria.soft) only add explanations and ranking signal.
"""
from __future__ import annotations

import datetime as dt

from .vocab import CONCEPT_LABELS, Criteria, region_ancestors, region_label

SUPPORTED = ("verified", "provider-reported")
GRAIN_ORDER = {"minute": 0, "event": 0, "hourly": 1, "daily": 2, "monthly": 3, "yearly": 4}


def _date(s: str | None) -> dt.date | None:
    try:
        return dt.date.fromisoformat(s[:10]) if s else None
    except ValueError:
        return None


def _fmt_month(d: dt.date | None) -> str:
    return d.strftime("%b %Y") if d else "?"


def span_text(t: dict) -> str:
    start, end = _date(t.get("start")), _date(t.get("end"))
    if not start:
        return "unknown start"
    right = "present" if t.get("ongoing") and not end else _fmt_month(end)
    return f"{_fmt_month(start)} – {right}"


def coverage_years(t: dict) -> float | None:
    start = _date(t.get("start"))
    if not start:
        return None
    end = _date(t.get("end")) or (dt.date.today() if t.get("ongoing") else None)
    return round((end - start).days / 365.25, 1) if end else None


def _status_word(status: str) -> str:
    return {"verified": "verified by this project", "provider-reported": "reported by the publisher"}.get(status, "unverified")


def _reason(key, label, outcome, text, evidence=None, required=True):
    return {"key": key, "label": label, "outcome": outcome, "text": text, "evidence": evidence, "required": required}


def check_field(rec: dict, concept: str, required: bool) -> dict:
    label = CONCEPT_LABELS.get(concept, concept)
    key = f"field:{concept}"
    fields = [f for f in rec.get("fields", []) if concept in f.get("concepts", [])]
    record_level = [f for f in fields if f.get("level", "record") == "record"]
    supported = [f for f in record_level if f.get("status") in SUPPORTED]
    complete = rec.get("schemaStatus") == "complete"
    if supported:
        names = ", ".join(f"`{f['name']}`" for f in supported[:3])
        first = supported[0]
        if concept == "latlon":
            text = f"Latitude and longitude are documented on each record ({names})."
        elif concept == "timestamp":
            desc = first.get("description", "").rstrip(".").lower() or "the time of each record"
            text = f"The timestamp field {names.split(', ')[0]} records {desc}."
            if len(supported) > 1:
                others = ", ".join("`{}`".format(f["name"]) for f in supported[1:3])
                text += f" Also: {others}."
        else:
            text = f"{label}: {names} — {first.get('description', '')}".rstrip(" —")
        status = "verified" if all(f.get("status") == "verified" for f in supported) else "provider-reported"
        return _reason(key, label, "met", text + f" ({_status_word(status)})", first.get("evidence") or rec.get("canonicalUrl"), required)
    if record_level:
        return _reason(key, label, "unverified", f"{label} may be present ({record_level[0]['name']}) but isn't confirmed.", None, required)
    if fields:
        f = fields[0]
        if f.get("level") == "input":
            text = f"{label} is an API input (`{f['name']}`): you request one location at a time, so individual records don't carry their own coordinates."
        elif f.get("level") == "grid":
            text = f"{label} describes grid cells, not individual events."
        else:
            text = f"{label} is derived, not stored on each record."
        return _reason(key, label, "failed" if complete else "unverified", text, f.get("evidence"), required)
    if complete:
        return _reason(key, label, "failed", f"No {label.lower()} field in the documented schema.", rec.get("canonicalUrl"), required)
    return _reason(key, label, "unverified", f"{label} isn't listed in the metadata indexed here. Check the source schema.", None, required)


def check_years(rec: dict, years: float, required: bool) -> dict:
    t = rec.get("coverage", {}).get("temporal", {})
    label = f"At least {years:g} year{'s' if years != 1 else ''} of data"
    if "static" in t.get("granularity", []):
        return _reason("min_years", label, "failed", "Not a time series - there is no observation period.", t.get("evidence"), required)
    if t.get("status") not in SUPPORTED or not t.get("start"):
        note = f" {t['note']}" if t.get("note") else ""
        return _reason("min_years", label, "unverified", f"Date coverage is unverified.{note}", t.get("evidence"), required)
    have = coverage_years(t)
    if have is None:
        return _reason("min_years", label, "unverified", f"Coverage starts {_fmt_month(_date(t['start']))}; the end date is unknown.", t.get("evidence"), required)
    if t.get("dependsOnRequest"):
        text = f"Available {span_text(t)} ({_status_word(t['status'])}); coverage depends on the dates and location you request."
        return _reason("min_years", label, "met" if have >= years else "failed", text, t.get("evidence"), required)
    outcome = "met" if have >= years else "failed"
    return _reason("min_years", label, outcome, f"Covers {span_text(t)}, about {have:g} year{'' if have == 1 else 's'} ({_status_word(t['status'])}).", t.get("evidence"), required)


def check_period(rec: dict, start: str | None, end: str | None, required: bool) -> dict:
    t = rec.get("coverage", {}).get("temporal", {})
    label = f"Covers {start or '…'} to {end or '…'}"
    want_s, want_e = _date(start), _date(end)
    have_s = _date(t.get("start"))
    have_e = _date(t.get("end")) or (dt.date.today() if t.get("ongoing") else None)
    if t.get("status") not in SUPPORTED or not have_s:
        return _reason("period", label, "unverified", "Date coverage is unverified.", t.get("evidence"), required)
    ok = (not want_s or have_s <= want_s) and (not want_e or (have_e is not None and have_e >= want_e))
    return _reason("period", label, "met" if ok else "failed", f"Covers {span_text(t)}.", t.get("evidence"), required)


def check_formats(rec: dict, wanted: list[str], required: bool) -> dict:
    f = rec.get("formats", {})
    label = " or ".join(w.upper() for w in wanted)
    have = [v.lower() for v in f.get("values", [])]
    if f.get("status") in SUPPORTED and set(have) & set(wanted):
        hit = sorted(set(have) & set(wanted))
        return _reason("formats", label, "met", f"Available as {', '.join(h.upper() for h in hit)} ({_status_word(f['status'])}).", f.get("evidence"), required)
    if not have or f.get("status") not in SUPPORTED:
        return _reason("formats", label, "unverified", "File formats are not documented here.", f.get("evidence"), required)
    listed = ", ".join(h.upper() for h in have)
    if not f.get("exhaustive", True):
        return _reason("formats", label, "unverified", f"Confirmed as {listed}; {label} wasn't checked.", f.get("evidence"), required)
    return _reason("formats", label, "failed", f"Offered as {listed}, not {label}.", f.get("evidence"), required)


def check_region(rec: dict, region: str, required: bool) -> dict:
    s = rec.get("coverage", {}).get("spatial", {})
    label = f"Covers {region_label(region)}"
    regions = s.get("regions", [])
    scope = s.get("scope", "unknown")
    if scope == "not-applicable":
        return _reason("region", label, "failed", "Not a geographic dataset.", s.get("evidence"), required)
    if s.get("status") not in SUPPORTED or (not regions and scope == "unknown"):
        return _reason("region", label, "unverified", "Geographic coverage is unverified.", s.get("evidence"), required)
    if "global" in regions:
        if scope == "global-point-query":
            text = f"Global: you request coordinates for {region_label(region)}. Values are a gridded estimate for that point."
        else:
            text = f"Global coverage ({s.get('description') or 'worldwide'}) includes {region_label(region)}."
        return _reason("region", label, "met", text, s.get("evidence"), required)
    want = region_ancestors(region)
    for r in regions:
        if r == region or region in region_ancestors(r):
            return _reason("region", label, "met", f"Area covered: {s.get('description') or region_label(r)}.", s.get("evidence"), required)
        if r in want:
            return _reason("region", label, "unverified",
                           f"Covers {region_label(r)}; check how much of it falls in {region_label(region)}.", s.get("evidence"), required)
    area = s.get("description") or ", ".join(map(region_label, regions))
    return _reason("region", label, "failed", f"Area covered: {area} - not {region_label(region)}.", s.get("evidence"), required)


def check_granularity(rec: dict, grain: str, required: bool) -> dict:
    t = rec.get("coverage", {}).get("temporal", {})
    label = f"{grain.title()} values"
    have = t.get("granularity", [])
    if not have or t.get("status") not in SUPPORTED and "static" not in have:
        return _reason("granularity", label, "unverified", "Time resolution is unverified.", t.get("evidence"), required)
    if grain in have:
        return _reason("granularity", label, "met", f"{grain.title()} values are available.", t.get("evidence"), required)
    finer = [h for h in have if GRAIN_ORDER.get(h, 99) < GRAIN_ORDER.get(grain, -1)]
    if finer:
        return _reason("granularity", label, "met", f"{finer[0].title()}-level data; aggregate it to {grain}.", t.get("evidence"), required)
    return _reason("granularity", label, "failed", f"Resolution is {', '.join(have)}.", t.get("evidence"), required)


def check_commercial(rec: dict, required: bool) -> dict:
    lic = rec.get("license", {})
    label = "Commercial reuse"
    name = lic.get("name") or "unknown license"
    use = lic.get("commercialUse", "unknown")
    note = f" {lic['note']}" if lic.get("note") else ""
    if use == "allowed" and lic.get("status") in SUPPORTED:
        return _reason("commercial", label, "met", f"{name} permits commercial reuse with attribution.", lic.get("url") or lic.get("evidence"), required)
    if use == "not-allowed":
        return _reason("commercial", label, "failed", f"{name}: commercial use is not permitted.{note}", lic.get("evidence") or lic.get("url"), required)
    if use == "conditional":
        return _reason("commercial", label, "unverified", f"{name}: commercial use has conditions.{note}", lic.get("evidence") or lic.get("url"), required)
    return _reason("commercial", label, "unverified", f"Reuse terms are unknown ({name}).{note}", lic.get("url"), required)


def evaluate(rec: dict, c: Criteria, period: tuple[str | None, str | None] | None = None) -> dict:
    reasons = []
    for concept in c.fields:
        reasons.append(check_field(rec, concept, c.is_required(f"field:{concept}")))
    if c.min_years:
        reasons.append(check_years(rec, c.min_years, c.is_required("min_years")))
    if period and (period[0] or period[1]):
        reasons.append(check_period(rec, period[0], period[1], c.is_required("period")))
    if c.formats:
        reasons.append(check_formats(rec, c.formats, c.is_required("formats")))
    if c.region:
        reasons.append(check_region(rec, c.region, c.is_required("region")))
    if c.granularity:
        reasons.append(check_granularity(rec, c.granularity, c.is_required("granularity")))
    if c.commercial:
        reasons.append(check_commercial(rec, c.is_required("commercial")))
    required = [r for r in reasons if r["required"]]
    if any(r["outcome"] == "failed" for r in required):
        fit = "does-not-meet"
    elif any(r["outcome"] == "unverified" for r in required):
        fit = "needs-verification"
    else:
        fit = "meets"
    return {"fit": fit, "reasons": reasons}
