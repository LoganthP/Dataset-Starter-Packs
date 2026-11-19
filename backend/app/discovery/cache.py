"""Download cache: one transfer, reused by Look inside, Run sample, Full analysis and reruns.

Keys combine the provider host, the asset path, the dataset version and the server's validator (ETag, else
Last-Modified, else size). Files fetched with a user's credentials (Kaggle) also include the user id, so they are
never served to anyone else. A changed ETag/version means a new key; the stale entry ages out.

Entries:  <key>.bin      a whole downloaded file
          <key>.json     metadata (url, validator, bytes, created) and, for ZIPs, the central-directory listing
          <key>/<member> single archive members fetched with HTTP ranges
Writes go to a temporary name and are renamed into place, so an interrupted transfer never looks complete.
Size cap: DSP_CACHE_MAX_BYTES (default 5 GB), least recently used first.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import time
import urllib.parse
from pathlib import Path

from .. import config

MAX_BYTES = int(float(os.getenv("DSP_CACHE_MAX_BYTES", "5000000000")))
ENABLED = os.getenv("DSP_CACHE", "1") == "1"
_lock = threading.Lock()


def root() -> Path:
    d = config.STATE_DIR / "cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def validator(info: dict) -> str | None:
    """The strongest version signal the server gave: ETag, else Last-Modified, else total size."""
    if info.get("etag"):
        return "etag:" + info["etag"]
    if info.get("last_modified"):
        return "lm:" + info["last_modified"]
    if info.get("bytes_total"):
        return "size:" + str(info["bytes_total"])
    return None


def key(url: str, info: dict, *, version: str | None = None, user: str | None = None) -> str | None:
    v = validator(info)
    if not ENABLED or not v:
        return None
    u = urllib.parse.urlsplit(url)
    raw = json.dumps([u.netloc, u.path, u.query, version, v, user])
    return hashlib.sha256(raw.encode()).hexdigest()[:40]


def _touch(p: Path) -> None:
    try:
        os.utime(p, None)
    except OSError:
        pass


def get_file(k: str | None) -> Path | None:
    if not k:
        return None
    p = root() / f"{k}.bin"
    if p.exists():
        _touch(p)
        return p
    return None


def put_file(k: str | None, src: Path, meta: dict) -> Path | None:
    """Move a completed download into the cache (hard link back to the run folder is the caller's job)."""
    if not k:
        return None
    dest = root() / f"{k}.bin"
    tmp = dest.with_suffix(f".tmp{os.getpid()}{threading.get_ident()}")
    try:
        try:
            os.replace(src, tmp)  # same filesystem (both under DSP_STATE_DIR): a rename, not a copy
        except OSError:
            shutil.copyfile(src, tmp)
            src.unlink(missing_ok=True)
        os.replace(tmp, dest)
        link_into(dest, src)  # the run keeps its path
        write_meta(k, {**read_meta(k), **meta, "bytes": dest.stat().st_size, "created": time.time()})
    finally:
        tmp.unlink(missing_ok=True)
    evict()
    return dest


def read_meta(k: str | None) -> dict:
    if not k:
        return {}
    p = root() / f"{k}.json"
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return {}


def write_meta(k: str | None, meta: dict) -> None:
    if not k:
        return
    p = root() / f"{k}.json"
    tmp = p.with_suffix(".jsontmp")
    tmp.write_text(json.dumps(meta))
    os.replace(tmp, p)


def member_path(k: str, name: str, crc: int) -> Path:
    safe = hashlib.sha256(f"{name}|{crc}".encode()).hexdigest()[:24] + "_" + Path(name).name[-80:]
    return root() / k / safe


def get_member(k: str | None, name: str, crc: int) -> Path | None:
    if not k:
        return None
    p = member_path(k, name, crc)
    if p.exists():
        _touch(p)
        return p
    return None


def put_member(k: str | None, name: str, crc: int, src: Path) -> None:
    if not k:
        return
    dest = member_path(k, name, crc)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    shutil.copyfile(src, tmp)
    os.replace(tmp, dest)


def link_into(cached: Path, dest: Path) -> Path:
    """Expose a cached file inside a run folder without copying when the filesystem allows."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.unlink(missing_ok=True)
    try:
        os.link(cached, dest)
    except OSError:
        shutil.copyfile(cached, dest)
    return dest


def evict(limit: int | None = None) -> None:
    limit = MAX_BYTES if limit is None else limit
    with _lock:
        entries = []
        for p in root().rglob("*"):
            if p.is_file() and not p.name.endswith((".json", ".jsontmp")):
                st = p.stat()
                entries.append((st.st_mtime, st.st_size, p))
        total = sum(e[1] for e in entries)
        for _, size, p in sorted(entries):
            if total <= limit:
                break
            p.unlink(missing_ok=True)
            total -= size


def clear() -> None:
    shutil.rmtree(root(), ignore_errors=True)
