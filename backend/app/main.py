"""Dataset Starter Packs API.

    uvicorn app.main:app --reload --port 8000      (from the backend/ folder)

Interactive docs at http://127.0.0.1:8000/docs
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import accounts, blob, catalog, config, db, durable, kaggle_connect, packaging, queueing, runner, sources
from .discovery import analysis, comparisons, dataimport, importer, limits, live, resolve, search
from .discovery import search as discovery
from .discovery import store as catalog_store
from .discovery.formats import registry as format_registry
from .discovery.vocab import CONCEPT_LABELS, REGIONS, parse_query


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init()
    report = catalog_store.load_seeds()
    analysis.recover_interrupted()
    for err in report["errors"]:
        print(f"[catalog] {err}", flush=True)
    if not config.ON_VERCEL:  # no background threads between serverless requests
        importer.start_scheduler()
    yield


app = FastAPI(title="Dataset Starter Packs API", version="0.2.0", lifespan=lifespan,
              description="Discover datasets by project goal, check why they fit, and run curated starter packs.")
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"], allow_credentials=True)


@app.middleware("http")
async def _viewer(request: Request, call_next):
    """Who is asking: analysis runs started by a signed-in user are visible only to that user."""
    token = analysis.VIEWER.set(accounts.user_id(request) if request.url.path.startswith("/api/") else analysis.ANY)
    try:
        return await call_next(request)
    finally:
        analysis.VIEWER.reset(token)


@app.exception_handler(catalog.PackNotFound)
def _pack_not_found(_: Request, exc: catalog.PackNotFound):
    return JSONResponse(status_code=404, content={"detail": f"Pack {exc.args[0]!r} not found"})


class RunRequest(BaseModel):
    mode: str = Field("sample", pattern="^(sample|real)$")
    params: dict[str, str | float | int | None] = Field(default_factory=dict)


# ---------------------------------------------------------------- meta
@app.get("/api/health")
def health():
    return {"ok": True, "python": sys.version.split()[0], "packs": len(catalog.list_packs()),
            "github_repo": config.GITHUB_REPO or None, "storage": durable.backend(), "platform": "vercel" if config.ON_VERCEL else "server",
            "runMode": config.RUN_MODE}


@app.get("/api/worker/status")
def worker_status():
    """Is anything there to run queued jobs? (heartbeats of `python -m app.worker`; see queueing.py)"""
    return queueing.status()


@app.get("/api/diagnostics")
def diagnostics(deep: bool = False):
    """Deployment self-check with no secrets in it: storage, run mode, worker, Blob. `?deep=1` also asks Blob whether
    this process's token works, and that every setting the worker must share with the API matches."""
    worker = queueing.status()
    mism = {"blob_token": "BLOB_READ_WRITE_TOKEN", "secret_key": "DSP_SECRET_KEY", "database": "DATABASE_URL"}
    out = {"storage": durable.backend(), "databaseEnv": config.DATABASE_ENV or None, "databaseId": queueing.db_fp(), "runMode": config.RUN_MODE, "packRuns": config.PACK_RUNS_ENABLED,
           "worker": worker, "blob": blob.status(),
           "secretKeySet": bool(os.getenv("DSP_SECRET_KEY")),
           "maxTransferBytes": limits.MAX_TRANSFER_BYTES,
           "problems": []}
    if config.RUN_MODE == "queue":
        if not durable.IS_POSTGRES:
            near = sorted(k for k in os.environ if "DATABASE_URL" in k or "POSTGRES_URL" in k)  # names only, never values
            out["problems"].append("Queue mode needs DATABASE_URL (Postgres) so the API and the worker share one database. "
                                   + (f"Found {', '.join(near)} but none usable; check that it holds a postgres:// URL."
                                      if near else "No database variable is set for this environment: connect Neon Postgres to the project "
                                      "(Storage tab, Production enabled) and redeploy."))
        if worker["state"] in ("none", "offline"):
            out["problems"].append(worker["message"])
        for w in worker.get("warnings", []):
            out["problems"].append(f"The worker and this app have different {mism[w]} values. Set the same one on both.")
    if deep:
        out["blob"]["remote"] = blob.check_remote()
        if blob.enabled() and not out["blob"]["remote"]["ok"]:
            out["problems"].append(out["blob"]["remote"]["message"])
    out["ok"] = not out["problems"]
    return out


def capabilities() -> dict:
    lim = limits.capabilities()
    return {"packRuns": config.PACK_RUNS_ENABLED, "storage": durable.backend(), "runMode": analysis.RUN_MODE,
            "worker": queueing.status() if config.RUN_MODE == "queue" else None,
            "uploadMode": "blob" if blob.enabled() else "direct", **lim,
            # Vercel Functions accept request bodies up to 100 MB; larger files go browser -> private Blob (multipart) when a store is connected.
            "directUploadMaxMB": min(95, lim["maxUploadMB"]) if config.ON_VERCEL else lim["maxUploadMB"],
            "kaggleOAuth": kaggle_connect.oauth_available(),
            "formats": [{"key": h.key, "label": h.label, "description": h.description} for h in format_registry.handlers()]}


@app.get("/api/stats")
def stats():
    packs = [p for p in catalog.list_packs() if "error" not in p]
    s = db.stats()
    s.update({
        "packs": len(packs),
        "providers": sorted({p["provider"] for p in packs}),
        "skills": sorted({skill for p in packs for skill in p["skills"]}),
        "source_check": {k: v for k, v in sources.latest().items() if k != "results"},
    })
    return s


# ---------------------------------------------------------------- packs
@app.get("/api/packs")
def list_packs():
    latest = db.stats()["latest_by_pack"]
    out = []
    for p in catalog.list_packs():
        p = dict(p)
        p["latest_run"] = latest.get(p["slug"])
        if "error" not in p:
            p["has_real_data"] = catalog.data_status(p["slug"])["has_real_data"]
        out.append(p)
    return out


@app.get("/api/packs/{slug}")
def get_pack(slug: str):
    meta = catalog.load_pack(slug)
    meta["documents"] = catalog.pack_documents(slug)
    meta["data_status"] = catalog.data_status(slug)
    meta["github_url"] = f"https://github.com/{config.GITHUB_REPO}/blob/main/packs/{slug}/starter.ipynb" if config.GITHUB_REPO else None
    return meta


@app.get("/api/packs/{slug}/data")
def get_data_status(slug: str):
    return catalog.data_status(slug)


@app.delete("/api/packs/{slug}/data")
def clear_data(slug: str):
    raw = catalog.pack_dir(slug) / "data" / "raw"
    if raw.exists():
        shutil.rmtree(raw)
    return catalog.data_status(slug)


@app.get("/api/packs/{slug}/assets/{name}")
def pack_asset(slug: str, name: str):
    path = (catalog.pack_dir(slug) / "assets" / name).resolve()
    if path.parent != (catalog.pack_dir(slug) / "assets").resolve() or not path.is_file():
        raise HTTPException(404, "Asset not found")
    return FileResponse(path)


@app.get("/api/packs/{slug}/notebook")
def download_notebook(slug: str):
    path = catalog.pack_dir(slug) / "starter.ipynb"
    return FileResponse(path, media_type="application/x-ipynb+json", filename=f"{slug}-starter.ipynb")


@app.get("/api/packs/{slug}/starter.zip")
def download_starter(slug: str):
    data = packaging.build_zip(catalog.pack_dir(slug))
    return Response(data, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{slug}-starter.zip"'})


@app.post("/api/packs/{slug}/upload")
async def upload_data(slug: str, file: UploadFile = File(...)):
    """Import manually downloaded source files (used by packs whose data needs a sign-in, e.g. Kaggle)."""
    meta = catalog.load_pack(slug)
    if meta["source"].get("access_method") != "kaggle":
        raise HTTPException(400, "This pack downloads its data automatically in real mode - no upload needed.")
    suffix = Path(file.filename or "upload.zip").suffix.lower()
    if suffix not in (".zip", ".csv"):
        raise HTTPException(400, "Upload the Kaggle ZIP (archive.zip) or one of the expected CSV files.")
    tmp_dir = Path(tempfile.mkdtemp(dir=config.STATE_DIR))
    target = tmp_dir / (Path(file.filename).name if suffix == ".csv" else "upload.zip")
    size = 0
    try:
        with open(target, "wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > config.max_upload_bytes():
                    raise HTTPException(413, f"File larger than {config.max_upload_bytes() / 1e9:.1f} GB (DSP_MAX_TRANSFER_BYTES)")
                out.write(chunk)
        proc = subprocess.run([config.PACK_PYTHON or sys.executable, "load_data.py", "--import", str(target)],
                              cwd=catalog.pack_dir(slug), capture_output=True, text=True, timeout=300)
        output = (proc.stdout + proc.stderr).strip()
        status = catalog.data_status(slug)
        if proc.returncode != 0 and not status["has_real_data"]:
            raise HTTPException(400, runner._last_error(output))
        missing = [f for f in status["expected_files"] if f not in {c["name"] for c in status["cached_files"]}]
        return {"ok": not missing, "missing": missing, "output": output[-3000:], "data_status": status}
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------------------------------------------------------------- runs
@app.post("/api/packs/{slug}/runs", status_code=202)
def create_run(slug: str, body: RunRequest):
    if not config.PACK_RUNS_ENABLED:
        raise HTTPException(503, "Starter-pack runs are turned off on this deployment: on Vercel they need DATABASE_URL (Postgres) so a worker "
                                 "can run them (see the README). Download the starter or the notebook to run it yourself.")
    try:
        return runner.submit(slug, body.mode, {k: v for k, v in body.params.items()})
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/runs")
def list_runs(slug: str | None = None, limit: int = Query(100, ge=1, le=500)):
    return db.list_runs(slug, limit)


def _run_or_404(run_id: str) -> dict:
    run = db.get(run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    return run


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    run = runner.with_queue(_run_or_404(run_id))
    run["results"] = runner.results(run_id) if run["status"] == "succeeded" else None
    return run


@app.get("/api/runs/{run_id}/log")
def get_log(run_id: str, offset: int = Query(0, ge=0)):
    _run_or_404(run_id)
    return runner.read_log(run_id, offset)


@app.get("/api/runs/{run_id}/files/{name}")
def get_run_file(run_id: str, name: str):
    _run_or_404(run_id)
    found = runner.read_file(run_id, name)
    if not found:
        raise HTTPException(404, "File not found")
    data, ctype = found
    if isinstance(data, bytes):  # produced by a worker and stored in the database
        return Response(data, media_type=ctype, headers={"Cache-Control": "private, max-age=3600"})
    return FileResponse(data)


@app.post("/api/runs/{run_id}/cancel")
def cancel_run(run_id: str):
    _run_or_404(run_id)
    return {"canceled": runner.cancel(run_id)}


@app.delete("/api/runs/{run_id}")
def delete_run(run_id: str):
    run = _run_or_404(run_id)
    if run["status"] in ("queued", "running"):
        raise HTTPException(409, "Cancel the run before deleting it.")
    shutil.rmtree(runner.run_dir(run_id), ignore_errors=True)
    db.delete(run_id)
    return {"deleted": run_id}


# ---------------------------------------------------------------- discovery
@app.get("/api/criteria/parse")
def parse_criteria(q: str = ""):
    """Turn a plain-language request into editable criteria (deterministic rules, see discovery/vocab.py)."""
    return parse_query(q).to_dict()


@app.get("/api/discover/meta")
def discover_meta():
    records = catalog_store.all_records()
    return {
        "total": len(records),
        "curated": sum(1 for r in records.values() if r.get("curated")),
        "reviewed": sum(1 for r in records.values() if r.get("reviewStatus") == "reviewed"),
        "providers": catalog_store.counts_by_provider(),
        "imports": importer.status(),
        "catalogHealth": catalog_store.health(),
        "liveProviders": live.provider_list(),
        "capabilities": capabilities(),
        "concepts": CONCEPT_LABELS,
        "regions": {k: v["label"] for k, v in REGIONS.items()},
        "examples": [
            "Traffic incidents with latitude, longitude and timestamps, at least one year, CSV",
            "Daily weather for Bengaluru over 10 years",
            "Beginner forecasting project with an offline sample",
            "CSV suitable for commercial reuse",
        ],
    }


@app.get("/api/datasets")
def list_datasets(request: Request):
    """Search with criteria + filters. Every parameter is a plain query string so the URL is shareable."""
    params = dict(request.query_params)
    try:
        return discovery.search(params)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/datasets/compare")
def compare_datasets(request: Request, ids: str = Query(..., description="Comma-separated, up to 3")):
    wanted = [i for i in ids.split(",") if i][:3]
    params = dict(request.query_params)
    out = [discovery.detail(i, params) for i in wanted]
    missing = [i for i, d in zip(wanted, out) if d is None]
    if missing:
        raise HTTPException(404, f"Unknown dataset id(s): {', '.join(missing)}")
    return {"items": out}


def _dataset_statuses(rec: dict) -> dict:
    link = rec.get("linkCheck")
    pack_check = None
    if rec.get("packId"):
        pack_check = next((r for r in sources.latest().get("results", []) if r["slug"] == rec["packId"]), None)
    responded = {"state": "unchecked", "detail": "No check yet. Run one to see if the source answers."}
    if link:
        responded = {"state": "ok" if link["ok"] else "error", "detail": link["detail"], "at": link["checked_at"], "http": link["http_status"]}
    elif pack_check:
        responded = {"state": "ok" if pack_check["status"] in ("ok", "manual") else "error",
                     "detail": "; ".join(p["detail"] for p in pack_check["probes"]), "at": pack_check["checked_at"]}
    reviewed = {"state": "ok" if rec.get("reviewStatus") == "reviewed" else "pending",
                "detail": f"Metadata reviewed {rec['lastVerifiedAt']}" if rec.get("lastVerifiedAt") and rec.get("reviewStatus") == "reviewed"
                else ("Found by live search; nobody has reviewed this metadata yet. Fields marked Verified come from a file you imported."
                      if rec.get("origin") == "live" else "Imported automatically; nobody has reviewed this metadata yet."), "at": rec.get("lastVerifiedAt")}
    sample = {"state": "not-applicable", "detail": "No starter pack yet, so there is no sample to run."}
    if rec.get("packId"):
        runs = [r for r in db.list_runs(rec["packId"], 50) if r["mode"] == "sample"]
        ok = next((r for r in runs if r["status"] == "succeeded"), None)
        sample = ({"state": "ok", "detail": ok.get("headline") or "Sample run succeeded.", "at": ok["finished_at"], "run_id": ok["id"]} if ok
                  else {"state": "pending", "detail": "The sample hasn't been run on this machine yet." if not runs else "The latest sample runs failed.",
                        "run_id": runs[0]["id"] if runs else None})
    return {"sourceResponded": responded, "metadataReviewed": reviewed, "sampleRan": sample}


@app.get("/api/datasets/{record_id}")
def get_dataset(record_id: str, request: Request):
    rec = discovery.detail(record_id, dict(request.query_params))
    if rec is None:
        raise HTTPException(404, f"Dataset {record_id!r} not found")
    rec["statuses"] = _dataset_statuses(rec)
    return rec


@app.post("/api/datasets/{record_id}/check")
def check_dataset_source(record_id: str):
    rec = catalog_store.all_records().get(record_id)
    if rec is None:
        raise HTTPException(404, f"Dataset {record_id!r} not found")
    result = sources.probe_link(rec["canonicalUrl"], kaggle=rec["provider"] == "Kaggle")
    catalog_store.set_link_check(record_id, result["ok"], result["status"], result["detail"])
    return result


# ---------------------------------------------------------------- live provider search
@app.get("/api/live/providers")
def live_providers():
    return live.provider_list()


@app.get("/api/live/search")
def live_search(provider: str, q: str = "", topic: str | None = None, refresh: bool = False):
    """Search one provider. The browser calls this once per provider in parallel and refreshes /api/datasets as each finishes."""
    try:
        return live.run(provider, q, refresh=refresh, topic=topic)
    except KeyError as exc:
        raise HTTPException(404, f"Unknown provider {provider!r}") from exc


# ---------------------------------------------------------------- preview + file import (on demand)
def _record_or_404(record_id: str) -> dict:
    rec = catalog_store.all_records().get(record_id)
    if rec is None:
        raise HTTPException(404, f"Dataset {record_id!r} not found")
    return rec


@app.get("/api/datasets/{record_id}/preview")
def dataset_preview(record_id: str):
    try:
        return dataimport.preview(_record_or_404(record_id))
    except dataimport.ImportError_ as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/datasets/{record_id}/files")
def dataset_files(record_id: str, request: Request, refresh: bool = False, offset: int = Query(0, ge=0),
                  limit: int = Query(80, ge=1, le=500), q: str | None = Query(None, max_length=120)):
    """Ask the provider for the dataset's files (HF repos recursively, Kaggle with the user's connection, Zenodo, ...).
    Paged: large repositories list thousands of files."""
    rec = _record_or_404(record_id)
    user = accounts.user_id(request)
    t0 = time.monotonic()
    try:
        res = resolve.resolve(rec, refresh=refresh, user=user)
    except Exception as exc:  # a provider error must not break the panel; the user can still upload
        res = {"files": [], "total": 0, "via": None, "signInRequired": False, "note": None, "errors": [f"{type(exc).__name__}: {exc}"]}
    sign_in = res["signInRequired"] or (bool(rec.get("access", {}).get("signInRequired")) and not res["files"])
    out = resolve.page(res, offset, limit, q)
    return {**out, "discoveryMs": int((time.monotonic() - t0) * 1000), "signInRequired": sign_in, "maxMB": round(limits.MAX_TRANSFER_BYTES / 2**20), "maxBytes": limits.MAX_TRANSFER_BYTES,
            "quickSampleBytes": limits.QUICK_MAX_BYTES, "unsupportedFormats": search.unsupported_formats(rec, res["files"]),
            "kaggle": kaggle_connect.status(user) if res.get("connect") == "kaggle" else None}


class InspectRequest(BaseModel):
    fileUrl: str


@app.post("/api/datasets/{record_id}/inspect")
def inspect_file(record_id: str, body: InspectRequest, request: Request, offset: int = Query(0, ge=0), limit: int = Query(300, ge=1, le=2000)):
    """Look inside a listed file before running anything: detected type, and for a ZIP its members (read through
    HTTP Range requests, without downloading the archive) plus the analysis the registry would choose."""
    from .discovery import archive as archive_mod
    from .discovery.formats import registry

    rec = _record_or_404(record_id)
    user = accounts.user_id(request)
    f = resolve.find(rec, body.fileUrl, user=user)
    if not f:
        raise HTTPException(404, "That file isn't listed for this dataset.")
    auth = kaggle_connect.auth_headers(user) if kaggle_connect.is_kaggle_url(f["url"]) else None
    try:
        info = analysis.fetch_mod.probe(f["url"], None, auth=auth)
    except dataimport.ImportError_ as exc:
        raise _analysis_error(exc, rec) from exc
    from .discovery import cache as cache_mod

    out = {"file": {k: f.get(k) for k in ("name", "url", "format", "bytes")}, "detected": info.get("detected"), "bytes": info["bytes_total"] or f.get("bytes"),
           "rangeReads": info.get("ranges", False), "members": None, "transferredBytes": 8192, "source": "remote"}
    # The same cache the runs use: a previous download or directory read makes this instant and free.
    ckey = cache_mod.key(f["url"], info, version=rec.get("sourceUpdatedAt"), user=user if auth else None)
    listing = cache_mod.read_meta(ckey).get("listing")
    cached_file = cache_mod.get_file(ckey)
    if info.get("detected") == "zip" and not listing and cached_file:
        listing = archive_mod.inspect_path(cached_file)
        cache_mod.write_meta(ckey, {**cache_mod.read_meta(ckey), "listing": listing})
    if listing:
        out["source"] = "cache"
    elif info.get("detected") == "zip" and info.get("ranges") and out["bytes"]:
        try:
            listing = archive_mod.inspect_remote(f["url"], out["bytes"], auth=auth)
        except dataimport.ImportError_ as exc:
            out["note"] = f"Couldn't list the archive remotely: {exc}"
            return out
        out["transferredBytes"] += listing.get("bytes_fetched", 0)
        cache_mod.write_meta(ckey, {**cache_mod.read_meta(ckey), "listing": listing, "url": f["url"]})
    elif info.get("detected") == "zip":
        out["note"] = (f"This server doesn't allow partial reads, so listing the archive needs the whole {limits.human(out['bytes'])} download. "
                       "Running it downloads the archive once and keeps it, so Look inside, samples and reruns reuse that copy.")
        out["fullDownloadRequired"] = True
    if listing:
        members = listing["members"]
        pl_sample = registry.plan(members, sample=True)
        pl_full = registry.plan(members, sample=False)
        out.update({"members": analysis._candidates(members)[offset: offset + limit], "memberCount": len(members),
                    "expandedBytes": listing["expanded_bytes"], "skipped": listing["skipped"][:20], **registry.describe(members),
                    "suggested": {"handler": pl_full["handler"].key, "label": pl_full["handler"].label, "scores": pl_full["scores"],
                                  "sampleFiles": len(pl_sample["selected"]), "sampleBytes": sum(m["size"] for m in pl_sample["selected"]),
                                  "sampleTransfer": sum(m.get("compressed") or m["size"] for m in pl_sample["selected"]),
                                  "fullFiles": len(pl_full["selected"]), "fullBytes": sum(m["size"] for m in pl_full["selected"]),
                                  "fullTransfer": sum(m.get("compressed") or m["size"] for m in pl_full["selected"])},
                    "cached": bool(cached_file),
                    "membersCached": bool(pl_full["selected"]) and all(cache_mod.get_member(ckey, m["name"], m.get("crc", 0)) for m in pl_full["selected"])})
    return out


def _analysis_error(exc: dataimport.ImportError_, rec: dict | None = None) -> HTTPException:
    """422 with {message, kind, detail} so the UI can offer the right next step (which limit, the size, what to do instead)."""
    kind = getattr(exc, "kind", "format")
    detail = getattr(exc, "detail", None) or {}
    if kind == "consent" and rec:
        detail = {**detail, "consentUrl": rec.get("canonicalUrl"), "actions": ["open_consent", "retry"]}
    return HTTPException(422, {"message": str(exc), "kind": kind, "detail": detail or None})


class AnalyzeRequest(BaseModel):
    fileUrl: str | None = None
    fileIndex: int | None = Field(default=None, ge=0)
    mode: Literal["sample", "full"] = "sample"
    dateField: str | None = Field(default=None, max_length=80, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    dateFrom: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    dateTo: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    prepare: bool = False  # "Prepare archive and run sample": download the whole archive, then sample it
    members: list[str] | None = Field(default=None, max_length=5000)  # archive members to analyze
    handler: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_-]{1,30}$")
    pairUrl: str | None = None  # the paired file (e.g. metadata/<prefix>_metadata.parquet)
    sheet: str | None = Field(default=None, max_length=100)  # Excel worksheet (default: the first)


def _params(body) -> dict:
    return {"dateField": body.dateField, "dateFrom": body.dateFrom, "dateTo": body.dateTo, "prepare": body.prepare or None,
            "members": body.members or None, "handler": body.handler, "pairUrl": body.pairUrl,
            "sheet": body.sheet}


@app.post("/api/datasets/{record_id}/analyze", status_code=202)
def analyze_listed_file(record_id: str, body: AnalyzeRequest, request: Request):
    """Check the file, then analyze it: mode=sample (first rows / a systematic image sample, 60 s) or full. Poll /api/analyses/{id}."""
    if not body.fileUrl and body.fileIndex is None:
        raise HTTPException(422, "Choose a file (fileUrl).")
    rec = _record_or_404(record_id)
    try:
        return {"runId": analysis.start_from_file(rec, url=body.fileUrl, index=body.fileIndex, mode=body.mode, params=_params(body),
                                                  user=accounts.user_id(request))}
    except dataimport.ImportError_ as exc:
        raise _analysis_error(exc, rec) from exc


class RetryRequest(BaseModel):
    mode: Literal["sample", "full"] | None = None
    prepare: bool | None = None
    members: list[str] | None = Field(default=None, max_length=5000)


@app.post("/api/analyses/{run_id}/cancel")
def cancel_analysis(run_id: str):
    """Stop a running analysis at its next checkpoint (between downloaded chunks, extracted files, image batches or stages)."""
    if not analysis.get(run_id):
        raise HTTPException(404, "Analysis not found")
    analysis.request_cancel(run_id)
    return {"cancelRequested": run_id}


@app.post("/api/analyses/{run_id}/retry", status_code=202)
def retry_analysis(run_id: str, body: RetryRequest, request: Request):
    """Analyze the same file again (a new run); optionally switch sample/full, prepare the archive, or choose members."""
    extra = {k: v for k, v in (("prepare", body.prepare), ("members", body.members)) if v is not None}
    if body.mode == "full":
        extra["prepare"] = None
    try:
        return {"runId": analysis.retry(run_id, body.mode, user=accounts.user_id(request), params=extra)}
    except dataimport.ImportError_ as exc:
        raise _analysis_error(exc) from exc


class BlobAnalyzeRequest(BaseModel):
    url: str
    name: str = Field(min_length=1, max_length=255)


@app.post("/api/datasets/{record_id}/analyze/blob", status_code=202)
def analyze_blob(record_id: str, body: BlobAnalyzeRequest, request: Request):
    """Analyze a file the browser uploaded directly to private Vercel Blob storage (multipart for large files)."""
    try:
        return {"runId": analysis.start_from_blob(_record_or_404(record_id), body.url, body.name, user=accounts.user_id(request))}
    except dataimport.ImportError_ as exc:
        raise _analysis_error(exc) from exc


@app.post("/api/blob/upload-token")
async def blob_upload_token(request: Request):
    """Token endpoint for @vercel/blob/client upload() (handleUploadUrl)."""
    if not blob.enabled():
        raise HTTPException(503, "Large uploads aren't set up: BLOB_READ_WRITE_TOKEN is missing on this deployment. "
                                 "Connect a private Blob store in Vercel (Storage) and redeploy.")
    if not blob.status()["tokenFormatOk"]:
        raise HTTPException(500, "BLOB_READ_WRITE_TOKEN isn't a Blob read/write token (it should start with vercel_blob_rw_).")
    try:
        body = await request.json()
    except ValueError as exc:
        raise HTTPException(400, "Expected a JSON event from @vercel/blob/client.") from exc
    if body.get("type") != "blob.generate-client-token":
        raise HTTPException(400, "Unsupported event")
    pathname = str((body.get("payload") or {}).get("pathname") or "")
    if not pathname.startswith("uploads/") or ".." in pathname:
        raise HTTPException(400, "Uploads go under uploads/<dataset>/.")
    # The token caps the object size, so the 2 GB transfer limit holds for browser -> Blob multipart uploads too.
    return JSONResponse({"type": "blob.generate-client-token",
                         "clientToken": blob.client_token(pathname, maximum_size_in_bytes=limits.MAX_TRANSFER_BYTES)},
                        headers={"Cache-Control": "no-store"})


@app.post("/api/datasets/{record_id}/analyze/upload", status_code=202)
async def analyze_upload(record_id: str, request: Request, file: UploadFile = File(...)):
    """Analyze a file you downloaded yourself. Any type: it is detected from its content, and archives are inspected."""
    rec = _record_or_404(record_id)
    declared = int(request.headers.get("content-length") or 0)
    if declared > limits.MAX_TRANSFER_BYTES + 1_000_000:
        raise HTTPException(413, {"message": f"This upload is {limits.human(declared)}, over the {limits.human(limits.MAX_TRANSFER_BYTES)} transfer limit "
                                             "(DSP_MAX_TRANSFER_BYTES).", "kind": "too_large",
                                  "detail": limits.detail("transfer", declared, estimated=True, actions=["open_source"])})
    name = Path(file.filename or "upload.bin").name
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(dir=config.STATE_DIR))
    target, size = tmp / name, 0
    with open(target, "wb") as out:
        while chunk := await file.read(1 << 20):
            size += len(chunk)
            if size > limits.MAX_TRANSFER_BYTES:
                shutil.rmtree(tmp, ignore_errors=True)
                raise HTTPException(413, {"message": f"The upload passed the {limits.human(limits.MAX_TRANSFER_BYTES)} transfer limit "
                                                     "(DSP_MAX_TRANSFER_BYTES).", "kind": "too_large",
                                          "detail": limits.detail("transfer", size, actions=["open_source"])})
            out.write(chunk)
    return {"runId": analysis.start_from_upload(rec, target, user=accounts.user_id(request))}


@app.get("/api/analyses")
def list_analyses(dataset_id: str | None = None, limit: int = Query(200, ge=1, le=500)):
    titles = {k: v["title"] for k, v in catalog_store.all_records().items()}
    return [{k: v for k, v in r.items() if k not in ("report", "log", "job", "summary")} | {"dataset_title": titles.get(r["dataset_id"], r["dataset_id"]),
            "rows": (r.get("summary") or {}).get("rows"), "coverage": (r.get("summary") or {}).get("coverage"),
            "kind": (r.get("summary") or {}).get("kind"), "scope": (r.get("summary") or {}).get("scope")}
            for r in analysis.list_runs(dataset_id, limit)]


@app.get("/api/analyses/{run_id}")
def get_analysis(run_id: str, view: Literal["full", "lite"] = "full"):
    """A run visible to whoever is asking (signed-in users see their own runs plus shared anonymous ones).
    view=lite leaves out the raw first rows; the Run view loads them (GET .../details) only when that section opens."""
    run = analysis.get(run_id)
    if not run:
        raise HTTPException(404, "Analysis not found")
    has_job = bool(run.pop("job", None))
    queued_for_worker = run["status"] == "queued" and has_job
    run.pop("summary", None)
    if queued_for_worker:  # where it is in line, and whether a worker is there to run it
        run["queue"] = queueing.queue_info("analysis_runs", run["created_at"], run_id)
    if view == "lite" and run.get("report"):
        run["report"] = {k: v for k, v in run["report"].items() if k != "preview"} | {"preview_deferred": len(run["report"].get("preview") or [])}
    rec = catalog_store.all_records().get(run["dataset_id"])
    run["dataset"] = {"id": run["dataset_id"], "title": rec["title"] if rec else run["dataset_id"], "exists": rec is not None}
    run["isLatest"] = analysis.latest_successful().get(run["dataset_id"], {}).get("runId") == run_id
    return run


@app.get("/api/analyses/{run_id}/details")
def analysis_details(run_id: str):
    """The heavy parts of a saved report, loaded on demand: the first rows."""
    run = analysis.get(run_id)
    if not run or not run.get("report"):
        raise HTTPException(404, "Analysis not found")
    return {"preview": run["report"].get("preview") or [], "columns": [c["name"] for c in run["report"].get("columns", [])]}


@app.get("/api/analyses/{run_id}/notebook")
def analysis_notebook(run_id: str):
    try:
        return Response(analysis.notebook(run_id), media_type="application/x-ipynb+json",
                        headers={"Content-Disposition": f'attachment; filename="analysis-{run_id}.ipynb"'})
    except FileNotFoundError as exc:
        raise HTTPException(404, "No notebook for this analysis") from exc


# ---------------------------------------------------------------- accounts
class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=1, max_length=200)


@app.post("/api/auth/signup", status_code=201)
def sign_up(body: Credentials, request: Request, response: Response):
    user = accounts.sign_up(body.email, body.password)
    accounts.start_session(response, request, user)
    return {"user": user}


@app.post("/api/auth/login")
def log_in(body: Credentials, request: Request, response: Response):
    user = accounts.log_in(body.email, body.password)
    accounts.start_session(response, request, user)
    return {"user": user}


@app.post("/api/auth/logout")
def log_out(request: Request, response: Response):
    accounts.end_session(response, request)
    return {"user": None}


@app.get("/api/auth/me")
def me(request: Request):
    return {"user": accounts.current(request)}


# ---------------------------------------------------------------- provider connections (Kaggle)
class KaggleToken(BaseModel):
    token: str | None = Field(default=None, max_length=500)
    username: str | None = Field(default=None, max_length=100)
    key: str | None = Field(default=None, max_length=200)
    kaggleJson: str | None = Field(default=None, max_length=2000)


@app.get("/api/connections/kaggle")
def kaggle_status(request: Request):
    return kaggle_connect.status(accounts.user_id(request))


@app.post("/api/connections/kaggle")
def kaggle_connect_token(body: KaggleToken, request: Request):
    """Connect (or reconnect) with an official Kaggle API token. Verified with Kaggle, then stored encrypted."""
    user = accounts.require(request)
    try:
        return kaggle_connect.connect_with_token(user["id"], token=body.token, username=body.username, key=body.key, kaggle_json=body.kaggleJson)
    except kaggle_connect.ConnectError as exc:
        raise HTTPException(422 if exc.kind in ("auth", "invalid") else 502, {"message": str(exc), "kind": exc.kind}) from exc
    finally:
        resolve._CACHE.clear()  # file lists depend on the connection


@app.delete("/api/connections/kaggle")
def kaggle_disconnect(request: Request):
    user = accounts.require(request)
    kaggle_connect.disconnect(user["id"])
    resolve._CACHE.clear()
    return kaggle_connect.status(user["id"])


@app.get("/api/kaggle/oauth/start")
def kaggle_oauth_start(request: Request, returnTo: str = "/settings"):
    user = accounts.require(request)
    try:
        return RedirectResponse(kaggle_connect.oauth_start(user["id"], returnTo), status_code=302)
    except kaggle_connect.ConnectError as exc:
        raise HTTPException(409, {"message": str(exc), "kind": exc.kind}) from exc


@app.get("/api/kaggle/oauth/callback")
def kaggle_oauth_callback(state: str = "", code: str = "", error: str = ""):
    if error or not code:
        return RedirectResponse(f"/settings?kaggle=error&reason={error or 'cancelled'}", status_code=302)
    try:
        _, back = kaggle_connect.oauth_callback(state, code)
    except kaggle_connect.ConnectError:
        return RedirectResponse("/settings?kaggle=error&reason=expired", status_code=302)
    resolve._CACHE.clear()
    return RedirectResponse(back + ("&" if "?" in back else "?") + "kaggle=connected", status_code=302)


# ---------------------------------------------------------------- comparisons
class ComparisonRequest(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=3)
    criteria: str = ""
    name: str | None = Field(default=None, max_length=120)


@app.get("/api/comparisons/current")
def current_comparison(ids: str, criteria: str = ""):
    try:
        return {"items": comparisons.build([i for i in ids.split(",") if i][:3], criteria)}
    except KeyError as exc:
        raise HTTPException(404, f"Unknown dataset id {exc.args[0]!r}") from exc


@app.post("/api/comparisons", status_code=201)
def save_comparison(body: ComparisonRequest):
    try:
        return comparisons.save(body.ids, body.criteria, body.name)
    except KeyError as exc:
        raise HTTPException(404, f"Unknown dataset id {exc.args[0]!r}") from exc


@app.get("/api/comparisons")
def list_comparisons():
    return comparisons.list_reports()


@app.get("/api/comparisons/{report_id}")
def get_comparison(report_id: str):
    rep = comparisons.get(report_id)
    if not rep:
        raise HTTPException(404, "Comparison not found")
    return rep


@app.delete("/api/comparisons/{report_id}")
def delete_comparison(report_id: str):
    comparisons.delete(report_id)
    return {"deleted": report_id}


@app.get("/api/imports")
def import_status():
    return importer.status()


@app.post("/api/imports/run", status_code=202)
def run_imports(source: str | None = None):
    return {"started": importer.start_background([source] if source else None)}


@app.post("/api/catalog/reload")
def reload_catalog():
    return catalog_store.load_seeds()


# ---------------------------------------------------------------- sources
@app.get("/api/sources")
def get_sources():
    return sources.latest()


@app.post("/api/sources/check", status_code=202)
def check_sources():
    return {"started": sources.start_background_check()}


# ---------------------------------------------------------------- built frontend (optional single-server mode)
if config.FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=config.FRONTEND_DIST / "assets"), name="frontend-assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(404)
        candidate = (config.FRONTEND_DIST / full_path).resolve()
        if full_path and candidate.is_file() and config.FRONTEND_DIST.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(config.FRONTEND_DIST / "index.html")
