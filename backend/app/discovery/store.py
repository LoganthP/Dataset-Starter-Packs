"""SQLite catalog index: records + FTS5 full-text table + per-source fetch status + link checks.

Seeds (catalog/records/*.json) and curated packs are the reviewed source of truth and are reloaded
on startup. Imported provider records are upserted by stable id and never overwrite reviewed records:
an import that matches a reviewed record (same id or same canonical URL) only refreshes its
lastFetchedAt / sourceUpdatedAt.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from .. import config, durable
from .schema import normalize

CATALOG_DIR = config.REPO_ROOT / "catalog"
RECORDS_DIR = CATALOG_DIR / "records"
DB_PATH = config.STATE_DIR / "catalog.sqlite3"
_lock = threading.RLock()
_cache: dict[str, dict] | None = None
_health: dict = {"loadedAt": None}
STALE_DAYS = 30

SCHEMA = """
create table if not exists records (
  id text primary key,
  json text not null,
  provider text not null,
  origin text not null,
  canonical_url text not null,
  content_hash text not null,
  indexed_at text not null
);
create index if not exists records_url on records(canonical_url);
create virtual table if not exists records_fts using fts5(
  id unindexed, title, tags, description, fields, publisher,
  tokenize = 'porter unicode61'
);
create table if not exists source_status (
  source text primary key,
  label text not null,
  status text not null,              -- ok | error | skipped | never
  detail text,
  last_attempt_at text,
  last_success_at text,
  records integer default 0
);
create table if not exists live_hits (
  query text not null,
  provider text not null,
  record_id text not null,
  rank integer not null,
  fetched_at text not null,
  primary key (query, provider, record_id)
);
create table if not exists live_runs (
  query text not null,
  provider text not null,
  status text not null,
  detail text,
  count integer default 0,
  ms integer default 0,
  fetched_at text not null,
  primary key (query, provider)
);
create table if not exists link_checks (
  record_id text primary key,
  ok integer not null,
  http_status integer,
  detail text,
  checked_at text not null
);
"""


def now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


@contextmanager
def connect():
    con = sqlite3.connect(DB_PATH, timeout=15)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def _invalidate():
    global _cache
    _cache = None


def _fts_row(rec: dict) -> tuple:
    fields = " ".join(f"{f['name']} {f.get('description', '')} {' '.join(f.get('concepts', []))}" for f in rec.get("fields", []))
    return (rec["id"], rec["title"], " ".join(rec.get("tags", [])), rec["description"], fields, f"{rec['publisher']} {rec['provider']}")


def _hash(rec: dict) -> str:
    return hashlib.sha256(json.dumps(rec, sort_keys=True).encode()).hexdigest()


def _write(con, rec: dict) -> None:
    con.execute("insert or replace into records (id, json, provider, origin, canonical_url, content_hash, indexed_at) values (?,?,?,?,?,?,?)",
                (rec["id"], json.dumps(rec), rec["provider"], rec["origin"], rec["canonicalUrl"].rstrip("/"), _hash(rec), now()))
    con.execute("delete from records_fts where id = ?", (rec["id"],))
    con.execute("insert into records_fts (id, title, tags, description, fields, publisher) values (?,?,?,?,?,?)", _fts_row(rec))


def _pack_meta() -> dict[str, dict]:
    out = {}
    for path in sorted(config.PACKS_DIR.glob("*/pack.json")):
        meta = json.loads(path.read_text(encoding="utf-8"))
        m = re.search(r"(\d+)\s*min", meta.get("estimated_time", ""))
        out[meta["slug"]] = {
            "slug": meta["slug"], "title": meta["title"], "difficulty": meta["difficulty"],
            "estimatedMinutes": int(m.group(1)) if m else None,
            "notebook": (path.parent / "starter.ipynb").exists(),
            "offlineSample": bool(meta.get("fixture")) and (path.parent / "fixtures").exists(),
            "lesson": meta["lesson"]["title"], "accent": meta.get("accent"),
            "hasPreview": (path.parent / "assets" / "preview.png").exists(),
            "expectedRuntime": meta.get("expected_runtime", {}),
        }
    return out


def _fallback_pack_record(slug: str, info: dict) -> dict:
    """A minimal record built from pack.json, so a curated pack is always searchable even if its
    catalog/records file is missing. Everything the pack.json doesn't state stays unknown."""
    from .adapters.kaggle import commercial_use

    meta = json.loads((config.PACKS_DIR / slug / "pack.json").read_text(encoding="utf-8"))
    src = meta["source"]
    method = {"direct-download": "direct-download", "api": "api", "kaggle": "sign-in"}.get(src.get("access_method"), "unknown")
    task = meta.get("task_type", "").lower()
    purposes = [p for p, words in {"forecasting": ("forecast", "time series"), "classification": ("classif",), "regression": ("regression",),
                                   "sql-analytics": ("sql",), "exploratory": ("explor", "astronomy")}.items() if any(w in task for w in words)]
    return normalize({
        "id": f"pack.{slug}", "title": meta["title"], "description": meta["tagline"], "publisher": src.get("publisher") or meta["provider"],
        "provider": meta["provider"], "providerId": slug, "canonicalUrl": src["dataset_page"],
        "sourceLinks": [{"label": "Official source", "url": src["dataset_page"]}],
        "tags": meta.get("skills", []), "purposes": purposes,
        "access": {"method": method, "signInRequired": bool(src.get("requires_credentials")), "status": "provider-reported", "evidence": f"packs/{slug}/pack.json"},
        "license": {"name": src.get("license"), "url": src.get("license_url"), "commercialUse": commercial_use(src.get("license")),
                    "status": "provider-reported", "evidence": f"packs/{slug}/pack.json"},
        "schemaStatus": "unknown", "origin": "pack", "reviewStatus": "reviewed", "packId": slug,
        "limitations": ["Built from pack.json because catalog/records has no record for this pack."],
    }) | {"curated": info}


def health() -> dict:
    return dict(_health)


def load_seeds() -> dict:
    """(Re)index reviewed records from catalog/records and attach curated pack info."""
    packs = _pack_meta()
    loaded, errors = [], []
    if not RECORDS_DIR.exists():
        errors.append(f"Catalog folder not found: {RECORDS_DIR}. Copy the repository's catalog/ folder next to backend/ and packs/.")
    for path in sorted(RECORDS_DIR.glob("*.json")):
        try:
            rec = normalize(json.loads(path.read_text(encoding="utf-8")))
            if path.stem != rec["id"]:
                raise ValueError(f"file name must equal id ({rec['id']})")
            if rec.get("packId"):
                if rec["packId"] not in packs:
                    raise ValueError(f"packId {rec['packId']} has no packs/<slug>/pack.json")
                rec["curated"] = packs[rec["packId"]]
            loaded.append(rec)
        except Exception as exc:  # one bad file must not hide the rest
            errors.append(f"{path.name}: {exc}")
    missing_packs = sorted(set(packs) - {r.get("packId") for r in loaded})
    for slug in missing_packs:
        try:
            loaded.append(_fallback_pack_record(slug, packs[slug]))
            errors.append(f"pack {slug} has no catalog record; indexed a minimal record from pack.json instead")
        except Exception as exc:
            errors.append(f"pack {slug}: could not build a fallback record ({exc})")
    with _lock, connect() as con:
        con.executescript(SCHEMA)
        ids = {r["id"] for r in loaded}
        stale = [row["id"] for row in con.execute("select id from records where origin in ('seed','pack')") if row["id"] not in ids]
        for rid in stale:
            con.execute("delete from records where id=?", (rid,))
            con.execute("delete from records_fts where id=?", (rid,))
        for rec in loaded:
            existing = con.execute("select json from records where id=?", (rec["id"],)).fetchone()
            if existing:  # keep fetch metadata gathered by imports
                old = json.loads(existing["json"])
                for k in ("lastFetchedAt",):
                    if old.get(k) and not rec.get(k):
                        rec[k] = old[k]
            _write(con, rec)
    _invalidate()
    _health.update({"recordsDir": str(RECORDS_DIR), "recordsDirExists": RECORDS_DIR.exists(),
                    "seedFiles": len(list(RECORDS_DIR.glob("*.json"))) if RECORDS_DIR.exists() else 0,
                    "packsFound": len(packs), "packsDir": str(config.PACKS_DIR), "loaded": len(loaded),
                    "fallbackPacks": missing_packs, "errors": errors, "loadedAt": now()})
    return {"loaded": len(loaded), "errors": errors}


def upsert_imported(records: list[dict]) -> dict:
    """Insert or refresh imported records with dedupe by id and canonical URL."""
    added = updated = merged = unchanged = 0
    with _lock, connect() as con:
        for raw in records:
            rec = normalize({**raw, "origin": "import", "reviewStatus": "unreviewed", "lastFetchedAt": now()})
            url = rec["canonicalUrl"].rstrip("/")
            same_id = con.execute("select id, origin, json from records where id=?", (rec["id"],)).fetchone()
            same_url = con.execute("select id, origin, json from records where canonical_url=? and id<>?", (url, rec["id"])).fetchone()
            target = same_id or same_url
            if target and target["origin"] in ("seed", "pack"):
                old = json.loads(target["json"])
                old["lastFetchedAt"] = rec["lastFetchedAt"]
                if rec.get("sourceUpdatedAt"):
                    old["sourceUpdatedAt"] = rec["sourceUpdatedAt"]
                _write(con, old)
                merged += 1
                continue
            if same_url and not same_id:  # same dataset under another imported id: keep the first one
                merged += 1
                continue
            if same_id:
                old = json.loads(same_id["json"])
                if _hash({**old, "lastFetchedAt": None}) == _hash({**rec, "lastFetchedAt": None}):
                    old["lastFetchedAt"] = rec["lastFetchedAt"]
                    _write(con, old)
                    unchanged += 1
                    continue
                updated += 1
            else:
                added += 1
            _write(con, rec)
    _invalidate()
    return {"added": added, "updated": updated, "merged_into_reviewed": merged, "unchanged": unchanged}


def _richness(rec: dict) -> int:
    known = sum(1 for k in ("formats", "license", "access") if (rec.get(k) or {}).get("status") != "unknown")
    t = (rec.get("coverage") or {}).get("temporal") or {}
    return 3 * len(rec.get("fields") or []) + 2 * known + (2 if t.get("status") != "unknown" else 0) + len(rec.get("description") or "") // 200


def upsert_live(records: list[dict], provider: str, query: str) -> list[str]:
    """Index live search results and remember which query found them (and at what rank).
    Dedupes by id, DOI and canonical URL; reviewed records are never overwritten; a sparser duplicate
    (e.g. a web hit for a Hugging Face page) never replaces a richer record."""
    from .adapters.common import norm_url

    ids: list[str] = []
    stamp = now()
    with _lock, connect() as con:
        con.executescript(SCHEMA)
        con.execute("delete from live_hits where query=? and provider=?", (query, provider))
        url_index = {norm_url(r["canonical_url"]): r["id"] for r in con.execute("select id, canonical_url from records")}
        for raw in records:
            try:
                rec = normalize({**raw, "origin": "live", "reviewStatus": "unreviewed", "lastFetchedAt": stamp})
            except Exception:
                continue  # one malformed upstream item must not sink the batch
            target_id = rec["id"]
            existing = con.execute("select id, origin, json from records where id=?", (target_id,)).fetchone()
            if not existing:
                dup = url_index.get(norm_url(rec["canonicalUrl"]))
                if not dup and rec.get("doi"):
                    row = con.execute("select id from records where json like ?", (f'%"doi": "{rec["doi"]}"%',)).fetchone()
                    dup = row["id"] if row else None
                if dup:
                    existing = con.execute("select id, origin, json from records where id=?", (dup,)).fetchone()
                    target_id = dup
            if existing:
                old = json.loads(existing["json"])
                if existing["origin"] in ("seed", "pack") or _richness(old) >= _richness(rec):
                    old["lastFetchedAt"] = stamp
                    _write(con, old)
                else:
                    _write(con, rec)
            else:
                _write(con, rec)
                url_index[norm_url(rec["canonicalUrl"])] = rec["id"]
            if target_id not in ids:
                ids.append(target_id)
                con.execute("insert or replace into live_hits values (?,?,?,?,?)", (query, provider, target_id, len(ids) - 1, stamp))
        shared = [(r["id"], r["json"]) for r in con.execute(
            f"select id, json from records where origin not in ('seed','pack') and id in ({','.join('?' * len(ids))})", ids)] if ids else []
    _invalidate()
    _share_live(query, provider, ids, shared, stamp)
    return ids


# ---------------------------------------------------------------- live results shared between instances
# Each serverless instance has its own /tmp, so the local cache above only knows what *this* instance searched. Results
# are mirrored to durable storage and pulled back on a miss: open, list files, upload and analyze then work on any instance.
_hydrated: dict[str, float] = {}
_HYDRATE_TTL = 20.0


def _shared_enabled() -> bool:
    return durable.IS_POSTGRES or SHARE_LOCAL


SHARE_LOCAL = False  # tests turn this on to exercise the shared path on SQLite


def _share_live(query: str, provider: str, ids: list[str], shared: list[tuple[str, str]], stamp: str) -> None:
    if not _shared_enabled():
        return
    try:
        durable.execute("delete from shared_live_hits where query=? and provider=?", (query, provider))
        durable.execute_many("insert into shared_live_records (id, json, updated_at) values (?,?,?) "
                             "on conflict (id) do update set json=excluded.json, updated_at=excluded.updated_at",
                             [(rid, js, stamp) for rid, js in shared])
        durable.execute_many("insert into shared_live_hits (query, provider, record_id, rank, fetched_at) values (?,?,?,?,?) "
                             "on conflict (query, provider, record_id) do update set rank=excluded.rank, fetched_at=excluded.fetched_at",
                             [(query, provider, rid, i, stamp) for i, rid in enumerate(ids)])
    except Exception as exc:  # the search itself worked; sharing is best effort
        _health["shareError"] = f"{type(exc).__name__}: {exc}"[:300]


def _write_shared(con, rows: list[dict]) -> int:
    """Write shared live records into the local cache without overwriting reviewed (seed/pack) records."""
    n = 0
    for row in rows:
        rec = json.loads(row["json"])
        have = con.execute("select origin from records where id=?", (rec["id"],)).fetchone()
        if have and have["origin"] in ("seed", "pack"):
            continue
        _write(con, rec)
        n += 1
    return n


def _shared_hits(query: str) -> list[dict] | None:
    """Shared hits for a query; records this instance hasn't cached yet are copied in. None if storage is unreachable."""
    try:
        hits = durable.query("select * from shared_live_hits where query=?", (query,))
        have = all_records()
        missing = sorted({h["record_id"] for h in hits} - have.keys())
        if missing:
            recs = durable.query(f"select json from shared_live_records where id in ({','.join('?' * len(missing))})", tuple(missing))
            with _lock, connect() as con:
                con.executescript(SCHEMA)
                _write_shared(con, recs)
            _invalidate()
        return hits
    except Exception:
        return None


def _hydrate_query(query: str) -> None:
    """Pull the shared hits (and their records) for one query into the local cache, at most every few seconds."""
    import time as _t

    if not _shared_enabled() or _t.monotonic() - _hydrated.get(query, -1e9) < _HYDRATE_TTL:
        return
    _hydrated[query] = _t.monotonic()
    try:
        hits = durable.query("select * from shared_live_hits where query=?", (query,))
        runs = durable.query("select * from shared_live_runs where query=?", (query,))
        ids = sorted({h["record_id"] for h in hits})
        recs = durable.query(f"select json from shared_live_records where id in ({','.join('?' * len(ids))})", tuple(ids)) if ids else []
    except Exception:
        return
    with _lock, connect() as con:
        con.executescript(SCHEMA)
        _write_shared(con, recs)
        for h in hits:
            con.execute("insert or replace into live_hits values (?,?,?,?,?)", (h["query"], h["provider"], h["record_id"], h["rank"], h["fetched_at"]))
        for r in runs:
            con.execute("insert or replace into live_runs values (?,?,?,?,?,?,?)",
                        (r["query"], r["provider"], r["status"], r["detail"], r["count"], r["ms"], r["fetched_at"]))
    _invalidate()


def get_record(record_id: str) -> dict | None:
    """One record by id: the local cache, then the shared live results (a dataset another instance found)."""
    rec = all_records().get(record_id)
    if rec is not None or not _shared_enabled():
        return rec
    try:
        rows = durable.query("select json from shared_live_records where id=?", (record_id,))
    except Exception:
        return None
    if not rows:
        return None
    with _lock, connect() as con:
        con.executescript(SCHEMA)
        _write_shared(con, rows)
    _invalidate()
    return all_records().get(record_id)


def record_live_run(query: str, provider: str, status: str, detail: str, count: int, ms: int) -> None:
    stamp = now()
    with _lock, connect() as con:
        con.execute("insert or replace into live_runs values (?,?,?,?,?,?,?)", (query, provider, status, detail[:400], count, ms, stamp))
    if _shared_enabled() and status == "ok":
        try:
            durable.execute("insert into shared_live_runs (query, provider, status, detail, count, ms, fetched_at) values (?,?,?,?,?,?,?) "
                            "on conflict (query, provider) do update set status=excluded.status, detail=excluded.detail, "
                            "count=excluded.count, ms=excluded.ms, fetched_at=excluded.fetched_at",
                            (query, provider, status, detail[:400], count, ms, stamp))
        except Exception:
            pass


def live_run(query: str, provider: str) -> dict | None:
    for attempt in (0, 1):
        with connect() as con:
            con.executescript(SCHEMA)
            row = con.execute("select * from live_runs where query=? and provider=?", (query, provider)).fetchone()
        if row or attempt:
            return dict(row) if row else None
        _hydrate_query(query)  # another instance may have searched this already: reuse its results
    return None


def live_hits(query: str) -> dict[str, dict]:
    """record_id -> best hit {provider, rank, fetched_at} for a normalized query."""
    if not query:
        return {}
    with connect() as con:
        con.executescript(SCHEMA)
        rows = con.execute("select * from live_hits where query=? order by rank", (query,)).fetchall()
    if _shared_enabled():  # what every instance found for this query (provider searches run on different instances)
        shared = _shared_hits(query)
        if shared is not None:
            rows = sorted({(r["provider"], r["record_id"]): r for r in [*map(dict, rows), *shared]}.values(), key=lambda r: r["rank"])
    out: dict[str, dict] = {}
    for r in rows:
        cur = out.get(r["record_id"])
        if cur is None or r["rank"] < cur["rank"]:
            out[r["record_id"]] = {"provider": r["provider"], "rank": r["rank"], "fetched_at": r["fetched_at"],
                                   "providers": (cur or {}).get("providers", []) + [r["provider"]]}
        else:
            cur["providers"].append(r["provider"])
    return out


def set_overlay(record_id: str, overlay: dict) -> None:
    durable.execute("insert into overlays (record_id, json, updated_at) values (?,?,?) "
                    "on conflict (record_id) do update set json=excluded.json, updated_at=excluded.updated_at",
                    (record_id, json.dumps(overlay), now()))
    _invalidate()


def overlays() -> dict[str, dict]:
    return {r["record_id"]: json.loads(r["json"]) for r in durable.query("select record_id, json from overlays")}


def save_curated_record(rec: dict) -> None:
    """Persist the record of an analyzed dataset (durable storage), without volatile fields."""
    clean = {k: v for k, v in rec.items() if k not in ("analysis", "stale", "verifiedImport", "liveHit")}
    durable.execute("insert into curated_records (id, json, updated_at) values (?,?,?) "
                    "on conflict (id) do update set json=excluded.json, updated_at=excluded.updated_at",
                    (rec["id"], json.dumps(clean), now()))
    _invalidate()


def curated_records() -> dict[str, dict]:
    return {r["id"]: json.loads(r["json"]) for r in durable.query("select id, json from curated_records")}


def apply_overlay(rec: dict, ov: dict) -> dict:
    """Facts verified by importing an actual file override weaker claims for the same record."""
    rec = json.loads(json.dumps(rec))
    if ov.get("temporal"):
        rec.setdefault("coverage", {})["temporal"] = {**rec.get("coverage", {}).get("temporal", {}), **ov["temporal"]}
    have = {f["name"].lower(): f for f in rec.get("fields", [])}
    for f in ov.get("fields", []):
        cur = have.get(f["name"].lower())
        if cur:
            cur.update({"status": "verified", "evidence": f["evidence"], "type": cur.get("type") or f.get("type"),
                        "concepts": sorted(set(cur.get("concepts", [])) | set(f.get("concepts", [])))})
        else:
            rec.setdefault("fields", []).append(f)
    if ov.get("formats"):
        vals = sorted(set(rec.get("formats", {}).get("values", [])) | set(ov["formats"]))
        rec["formats"] = {**rec.get("formats", {}), "values": vals, "status": "verified", "evidence": ov["evidence"],
                          "note": f"Confirmed by the imported file {ov.get('file')}."}
    if ov.get("fields") and rec.get("schemaStatus") == "unknown":
        rec["schemaStatus"] = "partial"
    rec["verifiedImport"] = {"importId": ov.get("importId"), "file": ov.get("file"), "at": ov.get("at")}
    return rec


def all_records() -> dict[str, dict]:
    global _cache
    with _lock:
        if _cache is None:
            with connect() as con:
                con.executescript(SCHEMA)
                rows = con.execute("select json from records").fetchall()
            recs = {}
            today = dt.datetime.now(dt.UTC)
            ovs = overlays()
            local = [json.loads(row["json"]) for row in rows]
            have = {r["id"] for r in local}
            # Analyzed datasets whose live-search entry is gone (new container, serverless cold start) come from durable storage.
            local += [r for rid, r in curated_records().items() if rid not in have]
            for rec in local:
                if rec["id"] in ovs:
                    rec = apply_overlay(rec, ovs[rec["id"]])
                fetched = rec.get("lastFetchedAt")
                rec["stale"] = bool(rec["origin"] in ("import", "live") and fetched and
                                    (today - dt.datetime.fromisoformat(fetched)).days > STALE_DAYS)
                recs[rec["id"]] = rec
            _cache = recs
        return _cache


def fts_scores(terms: list[str]) -> dict[str, float]:
    """BM25 relevance per record for OR-ed terms (prefix match). Higher is better."""
    if not terms:
        return {}
    expr = " OR ".join(f'"{t.replace(chr(34), "")}"*' for t in terms if t)
    with connect() as con:
        rows = con.execute(
            "select id, bm25(records_fts, 0.0, 10.0, 6.0, 3.0, 4.0, 1.0) as score from records_fts where records_fts match ?",
            (expr,),
        ).fetchall()
    return {r["id"]: -float(r["score"]) for r in rows}  # bm25 is lower-is-better


# ---------------------------------------------------------------- source + link status
def set_source_status(source: str, label: str, status: str, detail: str = "", records: int | None = None) -> None:
    with _lock, connect() as con:
        con.executescript(SCHEMA)
        prev = con.execute("select last_success_at, records from source_status where source=?", (source,)).fetchone()
        last_success = now() if status == "ok" else (prev["last_success_at"] if prev else None)
        count = records if records is not None else (prev["records"] if prev else 0)
        con.execute("insert or replace into source_status values (?,?,?,?,?,?,?)",
                    (source, label, status, detail[:500], now(), last_success, count))


def source_statuses() -> list[dict]:
    with connect() as con:
        con.executescript(SCHEMA)
        return [dict(r) for r in con.execute("select * from source_status order by source")]


def set_link_check(record_id: str, ok: bool, http_status: int | None, detail: str) -> None:
    with _lock, connect() as con:
        con.execute("insert or replace into link_checks values (?,?,?,?,?)", (record_id, int(ok), http_status, detail[:300], now()))


def link_checks() -> dict[str, dict]:
    with connect() as con:
        con.executescript(SCHEMA)
        return {r["record_id"]: {**dict(r), "ok": bool(r["ok"])} for r in con.execute("select * from link_checks")}


def counts_by_provider() -> dict[str, int]:
    out: dict[str, int] = {}
    for r in all_records().values():
        out[r["provider"]] = out.get(r["provider"], 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def seed_path(record_id: str) -> Path:
    return RECORDS_DIR / f"{record_id}.json"
