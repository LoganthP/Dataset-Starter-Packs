"""Archives: list without trusting them, then expand only what a run needs, within a budget.

inspect()        Reads the ZIP central directory: names, declared sizes, compression ratio. Rejects unsafe
                 entries (absolute paths, "..", drive letters, symlinks) and archives with too many entries.
extract()        Streams the chosen members to disk in 1 MiB chunks and counts the bytes actually written,
                 so a member that lies about its size still stops at the extraction budget.
RemoteZip        A seekable file over HTTP Range requests: lists a remote ZIP (and reads small members)
                 without downloading the whole archive, when the server supports ranges.
open_compressed  .gz and .Z (Unix compress) single files, decompressed with the same budget.
"""
from __future__ import annotations

import gzip
import io
import posixpath
import re
import shutil
import stat
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from . import limits
from .fetch import FetchError, headers_for

JUNK = re.compile(r"(^|/)(__MACOSX|\.DS_Store|Thumbs\.db|\._[^/]*)($|/)")


def safe_name(name: str) -> str | None:
    """Normalized relative path, or None when the entry would escape the extraction folder."""
    n = name.replace("\\", "/")
    if n.startswith("/") or re.match(r"^[A-Za-z]:", n) or "\x00" in n:
        return None
    norm = posixpath.normpath(n)
    if norm in (".", "") or norm.startswith("../") or norm == ".." or "/../" in f"/{norm}/":
        return None
    return norm


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    return info.create_system == 3 and stat.S_ISLNK(info.external_attr >> 16)


def inspect_zip(zf: zipfile.ZipFile, archive_bytes: int | None = None) -> dict:
    """{members:[{name,size,compressed,ext}], skipped:[{name,reason}], expanded_bytes, count}."""
    from .formats.registry import type_from_name

    infos = zf.infolist()
    if len(infos) > limits.MAX_ARCHIVE_MEMBERS:
        raise FetchError(f"The archive lists {len(infos):,} entries, over the {limits.MAX_ARCHIVE_MEMBERS:,}-entry limit (DSP_MAX_ARCHIVE_MEMBERS).",
                         "too_large", limits.detail("members", None, count=len(infos), actions=["open_source"]))
    members, skipped, expanded = [], [], 0
    for info in infos:
        if info.is_dir() or JUNK.search(info.filename):
            continue
        name = safe_name(info.filename)
        if name is None:
            skipped.append({"name": info.filename[:200], "reason": "unsafe path (absolute or outside the archive)"})
            continue
        if _is_symlink(info):
            skipped.append({"name": name, "reason": "symbolic link"})
            continue
        if info.flag_bits & 0x1:
            skipped.append({"name": name, "reason": "encrypted"})
            continue
        expanded += info.file_size
        members.append({"name": name, "size": info.file_size, "compressed": info.compress_size, "type": type_from_name(name),
                        "offset": info.header_offset, "method": info.compress_type, "crc": info.CRC})
    return {"members": members, "skipped": skipped, "expanded_bytes": expanded, "count": len(members), "archive_bytes": archive_bytes}


def inspect_path(path: Path) -> dict:
    try:
        with zipfile.ZipFile(path) as zf:
            return inspect_zip(zf, path.stat().st_size)
    except zipfile.BadZipFile as exc:
        raise FetchError(f"The ZIP is damaged or incomplete: {exc}.", "format") from exc


def check_budget(selected: list[dict], *, already: int = 0) -> int:
    """Declared expanded size of the selection; raises before anything is written when it's over budget."""
    total = already + sum(m["size"] for m in selected)
    if total > limits.MAX_EXTRACT_BYTES:
        raise FetchError(f"The selected files expand to {limits.human(total)}, over the {limits.human(limits.MAX_EXTRACT_BYTES)} "
                         "extraction budget (DSP_MAX_EXTRACT_BYTES). Nothing was extracted. Choose fewer files or run a sample.",
                         "too_large", limits.detail("extract", total, estimated=True, actions=["select_member", "run_sample"]))
    return total


def extract(path: Path, names: list[str], dest: Path, *, progress=None, cancel=None, deadline: float | None = None) -> dict[str, Path]:
    """Expand the named members under dest (paths re-validated). Returns name -> local path."""
    dest.mkdir(parents=True, exist_ok=True)
    out: dict[str, Path] = {}
    written, last = 0, 0.0
    with zipfile.ZipFile(path) as zf:
        by_name = {safe_name(i.filename): i for i in zf.infolist() if not i.is_dir()}
        declared = sum(by_name[n].file_size for n in names if n in by_name)
        for i, name in enumerate(names):
            info = by_name.get(name)
            if info is None or _is_symlink(info):
                continue
            target = dest / name
            if dest.resolve() not in target.resolve().parents:
                raise FetchError(f"Refused to extract {name}: it would land outside the run folder.", "format")
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as fh:
                while block := src.read(1 << 20):
                    written += len(block)
                    if written > limits.MAX_EXTRACT_BYTES:
                        raise FetchError(f"Expanding the archive passed the {limits.human(limits.MAX_EXTRACT_BYTES)} extraction budget "
                                         f"(DSP_MAX_EXTRACT_BYTES) at {name}. The files are larger than the archive declared. Extraction stopped.",
                                         "too_large", limits.detail("extract", written, actions=["select_member", "run_sample"]))
                    fh.write(block)
                    if deadline is not None and time.monotonic() > deadline:
                        raise FetchError(f"Timed out while extracting ({limits.human(written)} written).", "timeout")
            out[name] = target
            now = time.monotonic()
            if (progress or cancel) and (now - last > 0.5 or i == len(names) - 1):
                last = now
                if cancel:
                    cancel()
                if progress:
                    progress(i + 1, len(names), written, declared)
    return out


# ---------------------------------------------------------------- remote listing over HTTP Range
class RemoteZip(io.RawIOBase):
    """Read-only, seekable view of a remote file through Range requests. Small reads (the ZIP directory) use
    cached 64 KiB blocks; large reads (member data) go out as one request for exactly the bytes needed."""

    BLOCK = 1 << 16

    def __init__(self, url: str, size: int, *, auth: dict | None = None, timeout: float = 20, max_requests: int = 400, cancel=None):
        super().__init__()
        self.url, self.size, self.auth, self.timeout = url, size, auth, timeout
        self.pos, self.cache, self.requests, self.max_requests = 0, {}, 0, max_requests
        self.bytes_fetched, self.cancel, self.on_bytes = 0, cancel, None

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.pos

    def seek(self, offset: int, whence: int = 0) -> int:
        self.pos = {0: offset, 1: self.pos + offset, 2: self.size + offset}[whence]
        return self.pos

    def _range(self, start: int, end: int) -> bytes:
        if self.requests >= self.max_requests:
            raise FetchError("Reading the remote archive needed too many requests; download it instead.", "network")
        if self.cancel:
            self.cancel()
        req = urllib.request.Request(self.url, headers={**headers_for(self.url, self.auth), "Range": f"bytes={start}-{end}"})
        self.requests += 1
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if resp.status != 206:
                    raise FetchError("The server doesn't support ranged reads, so the archive can't be read without downloading it.", "network")
                data = resp.read()
        except urllib.error.URLError as exc:
            raise FetchError(f"Couldn't read the remote archive: {getattr(exc, 'reason', exc)}.", "network") from exc
        self.bytes_fetched += len(data)
        if self.on_bytes:
            self.on_bytes(self.bytes_fetched)
        return data

    def _block(self, idx: int) -> bytes:
        if idx in self.cache:
            return self.cache[idx]
        start = idx * self.BLOCK
        data = self._range(start, min(self.size, start + self.BLOCK) - 1)
        if len(self.cache) > 256:
            self.cache.clear()
        self.cache[idx] = data
        return data

    def read(self, n: int = -1) -> bytes:
        if n is None or n < 0:
            n = self.size - self.pos
        n = max(0, min(n, self.size - self.pos))
        if n > 2 * self.BLOCK:  # member data: one request for exactly these bytes
            data = self._range(self.pos, self.pos + n - 1)
            self.pos += len(data)
            return data
        out = bytearray()
        while n > 0:
            idx, off = divmod(self.pos, self.BLOCK)
            chunk = self._block(idx)[off: off + n]
            if not chunk:
                break
            out += chunk
            self.pos += len(chunk)
            n -= len(chunk)
        return bytes(out)

    def readinto(self, b) -> int:
        data = self.read(len(b))
        b[: len(data)] = data
        return len(data)


def inspect_remote(url: str, size: int, auth: dict | None = None, rz: RemoteZip | None = None) -> dict:
    rz = rz or RemoteZip(url, size, auth=auth)
    with zipfile.ZipFile(rz) as zf:
        out = inspect_zip(zf, size)
    out["bytes_fetched"], out["requests"] = rz.bytes_fetched, rz.requests
    return out


def _direct_member(rz: RemoteZip, m: dict, target: Path) -> bool:
    """One ranged request per member, using the offsets from a saved directory listing: the local header and the
    compressed bytes, decompressed here. False when the member needs the generic path (other compression, encryption)."""
    import struct
    import zlib

    if m.get("offset") is None or m.get("method") not in (0, 8):
        return False
    slack = 30 + len(m["name"].encode()) + 1024
    end = min(rz.size, m["offset"] + slack + m["compressed"]) - 1
    blob = rz._range(m["offset"], end)
    if blob[:4] != b"PK\x03\x04":
        return False
    flags, method = struct.unpack("<HH", blob[6:10])
    nlen, xlen = struct.unpack("<HH", blob[26:30])
    if flags & 0x1 or method != m["method"]:
        return False
    start = 30 + nlen + xlen
    if len(blob) < start + m["compressed"]:
        blob += rz._range(m["offset"] + len(blob), m["offset"] + start + m["compressed"] - 1)
    raw = blob[start: start + m["compressed"]]
    data = raw if method == 0 else zlib.decompressobj(-15).decompress(raw)
    if len(data) != m["size"] or (zlib.crc32(data) & 0xFFFFFFFF) != m["crc"]:
        raise FetchError(f"{m['name']} didn't match the archive's checksum after a ranged read. Retry the run.", "network")
    part = target.with_name(target.name + ".part")
    part.write_bytes(data)
    part.replace(target)
    return True


def fetch_members(url: str, size: int, names: list[str], dest: Path, *, auth: dict | None = None, cache_key: str | None = None,
                  progress=None, cancel=None, deadline: float | None = None, rz: RemoteZip | None = None, listing: dict | None = None) -> dict:
    """Retrieve only the named members of a remote ZIP with HTTP ranges (and the member cache).
    Returns {paths: name -> Path, bytes_fetched, requests, cached}."""
    from . import cache

    dest.mkdir(parents=True, exist_ok=True)
    if rz is None:
        rz = RemoteZip(url, size, auth=auth, cancel=cancel, max_requests=200 + 4 * len(names))
    else:  # the reader that listed the directory: its cached blocks are reused
        rz.cancel, rz.max_requests = cancel, rz.requests + 200 + 4 * len(names)
    start_bytes, start_requests = rz.bytes_fetched, rz.requests
    paths: dict[str, Path] = {}
    cached = written = 0
    # Fast path: a known directory (from Look inside or an earlier run) and small members -> one request each, no directory re-read.
    known = {m["name"]: m for m in (listing or {}).get("members", [])}
    if known and all(n in known and known[n].get("offset") is not None and known[n]["size"] <= 64 * 2**20 for n in names):
        declared = sum(known[n]["compressed"] for n in names)
        for i, name in enumerate(names):
            m = known[name]
            target = dest / name
            if dest.resolve() not in target.resolve().parents:
                raise FetchError(f"Refused to extract {name}: it would land outside the run folder.", "format")
            target.parent.mkdir(parents=True, exist_ok=True)
            hit = cache.get_member(cache_key, name, m["crc"])
            if hit:
                cache.link_into(hit, target)
                cached += 1
            elif _direct_member(rz, m, target):
                cache.put_member(cache_key, name, m["crc"], target)
            else:
                break
            paths[name] = target
            if progress:
                progress(i + 1, len(names), rz.bytes_fetched - start_bytes, declared)
        else:
            return {"paths": paths, "bytes_fetched": rz.bytes_fetched - start_bytes, "requests": rz.requests - start_requests, "cached": cached}
    with zipfile.ZipFile(rz) as zf:
        by_name = {safe_name(i.filename): i for i in zf.infolist() if not i.is_dir()}
        declared = sum(by_name[n].compress_size for n in names if n in by_name)
        for i, name in enumerate(names):
            info = by_name.get(name)
            if info is None or _is_symlink(info):
                continue
            target = dest / name
            if dest.resolve() not in target.resolve().parents:
                raise FetchError(f"Refused to extract {name}: it would land outside the run folder.", "format")
            target.parent.mkdir(parents=True, exist_ok=True)
            hit = cache.get_member(cache_key, name, info.CRC)
            if hit:
                cache.link_into(hit, target)
                cached += 1
            else:
                part = target.with_name(target.name + ".part")
                try:
                    with zf.open(info) as src, open(part, "wb") as fh:
                        while block := src.read(1 << 22):
                            written += len(block)
                            if written > limits.MAX_EXTRACT_BYTES:
                                raise FetchError(f"Expanding the selected files passed the {limits.human(limits.MAX_EXTRACT_BYTES)} extraction budget.",
                                                 "too_large", limits.detail("extract", written, actions=["select_member", "run_sample"]))
                            fh.write(block)
                            if deadline is not None and time.monotonic() > deadline:
                                raise FetchError(f"Timed out while reading archive members ({limits.human(rz.bytes_fetched)} received).", "timeout")
                    part.replace(target)
                finally:
                    part.unlink(missing_ok=True)
                cache.put_member(cache_key, name, info.CRC, target)
            paths[name] = target
            if progress:
                progress(i + 1, len(names), rz.bytes_fetched, declared)
    return {"paths": paths, "bytes_fetched": rz.bytes_fetched - start_bytes, "requests": rz.requests - start_requests, "cached": cached}


# ---------------------------------------------------------------- single-file compression
def decompress(path: Path, dest: Path, *, kind: str) -> Path:
    """gzip, bzip2, xz or Unix compress (.Z) -> dest, counted against the extraction budget."""
    written = 0
    if kind == "gzip":
        src = gzip.open(path, "rb")
    elif kind == "bzip2":
        import bz2

        src = bz2.open(path, "rb")
    elif kind == "xz":
        import lzma

        src = lzma.open(path, "rb")
    else:
        try:
            import unlzw3
        except ImportError as exc:  # pragma: no cover - listed in requirements
            raise FetchError("This file uses Unix compress (.Z); install unlzw3 to read it.", "format") from exc
        if path.stat().st_size > limits.MAX_EXTRACT_BYTES // 4:
            raise FetchError("This .Z file is too large to expand in memory.", "too_large",
                             limits.detail("extract", path.stat().st_size * 4, estimated=True, actions=["open_source"]))
        src = io.BytesIO(unlzw3.unlzw(path.read_bytes()))
    with src, open(dest, "wb") as out:
        while block := src.read(1 << 20):
            written += len(block)
            if written > limits.MAX_EXTRACT_BYTES:
                raise FetchError(f"Decompressing passed the {limits.human(limits.MAX_EXTRACT_BYTES)} extraction budget (DSP_MAX_EXTRACT_BYTES).",
                                 "too_large", limits.detail("extract", written, actions=["open_source"]))
            out.write(block)
    return dest


# ---------------------------------------------------------------- other archive kinds -> one ZIP
# Tar (plain, gzip, bzip2, xz), 7-Zip and ZIPs inside a ZIP are repacked into a single uncompressed ZIP so the ZIP path
# (listing, member picker, handler choice, budgets) handles them unchanged. Members are validated like ZIP members:
# no absolute paths, no "..", no links, junk skipped, and every byte counts against the extraction budget.
ARCHIVE_TYPES = ("zip", "tar", "7z")
_NESTED = re.compile(r"\.(zip|tar|tgz|tbz2|txz|tar\.gz|tar\.bz2|tar\.xz|7z)$", re.I)


class _Budget:
    def __init__(self, deadline: float | None, cancel):
        self.written, self.deadline, self.cancel = 0, deadline, cancel

    def add(self, n: int, name: str) -> None:
        self.written += n
        if self.written > limits.MAX_EXTRACT_BYTES:
            raise FetchError(f"Expanding the archive passed the {limits.human(limits.MAX_EXTRACT_BYTES)} extraction budget "
                             f"(DSP_MAX_EXTRACT_BYTES) at {name}. Extraction stopped.", "too_large",
                             limits.detail("extract", self.written, actions=["select_member", "run_sample"]))
        if self.deadline is not None and time.monotonic() > self.deadline:
            raise FetchError("Ran out of time while expanding the archive.", "timeout")
        if self.cancel:
            self.cancel()


def _copy_into(zout: zipfile.ZipFile, name: str, src, budget: _Budget) -> None:
    with zout.open(zipfile.ZipInfo(name, date_time=(2000, 1, 1, 0, 0, 0)), "w", force_zip64=True) as dst:
        while block := src.read(1 << 20):
            budget.add(len(block), name)
            dst.write(block)


def _tar_into(tar_path: Path, zout: zipfile.ZipFile, prefix: str, budget: _Budget) -> int:
    import tarfile

    n = 0
    try:
        with tarfile.open(tar_path, "r:*") as tf:
            for ti in tf:
                if not ti.isfile():  # links, devices and folders are skipped
                    continue
                name = safe_name(ti.name)
                if not name or JUNK.search(name):
                    continue
                src = tf.extractfile(ti)
                if src is None:
                    continue
                with src:
                    _copy_into(zout, prefix + name, src, budget)
                n += 1
    except (tarfile.TarError, EOFError, OSError) as exc:
        raise FetchError(f"The tar archive is damaged or incomplete: {exc}.", "format") from exc
    return n


def _sevenzip_into(path: Path, zout: zipfile.ZipFile, prefix: str, budget: _Budget, work: Path) -> int:
    try:
        import py7zr
    except ImportError as exc:
        raise FetchError("7-Zip archives need the py7zr package, which this deployment doesn't include (it is installed in the Docker "
                         "worker). Extract the archive on your computer and upload the data files, or a ZIP of them.", "format") from exc
    tmp = work / "_7z"
    tmp.mkdir(parents=True, exist_ok=True)
    try:
        with py7zr.SevenZipFile(path, "r") as z:
            infos = [i for i in z.list() if not i.is_directory]
            total = sum(i.uncompressed or 0 for i in infos)
            if budget.written + total > limits.MAX_EXTRACT_BYTES:
                budget.add(total, path.name)
            z.extractall(path=tmp)
    except FetchError:
        raise
    except Exception as exc:
        raise FetchError(f"The 7-Zip archive couldn't be read: {exc}.", "format") from exc
    n = 0
    for f in sorted(p for p in tmp.rglob("*") if p.is_file() and not p.is_symlink()):
        name = safe_name(f.relative_to(tmp).as_posix())
        if not name or JUNK.search(name):
            continue
        with open(f, "rb") as src:
            _copy_into(zout, prefix + name, src, budget)
        n += 1
    shutil.rmtree(tmp, ignore_errors=True)
    return n


def repack(path: Path, kind: str, work: Path, *, deadline: float | None = None, cancel=None, log=None) -> Path:
    """tar / 7z / a ZIP whose data sits in inner archives -> one flat ZIP (inner archives expanded one level)."""
    work.mkdir(parents=True, exist_ok=True)
    out = work / (re.sub(r"\.(zip|tar|tgz|tbz2|txz|gz|bz2|xz|7z)$", "", path.name, flags=re.I) + ".repacked.zip")
    budget = _Budget(deadline, cancel)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED, allowZip64=True) as zout:
        if kind == "tar":
            n = _tar_into(path, zout, "", budget)
        elif kind == "7z":
            n = _sevenzip_into(path, zout, "", budget, work)
        else:  # zip with inner archives
            n = 0
            with zipfile.ZipFile(path) as zin:
                for info in zin.infolist():
                    name = safe_name(info.filename)
                    if info.is_dir() or not name or JUNK.search(name) or _is_symlink(info):
                        continue
                    if _NESTED.search(name):
                        inner = work / "_inner" / name
                        inner.parent.mkdir(parents=True, exist_ok=True)
                        with zin.open(info) as src, open(inner, "wb") as fh:
                            while block := src.read(1 << 20):
                                budget.add(len(block), name)
                                fh.write(block)
                        prefix = re.sub(_NESTED, "", name) + "/"
                        if zipfile.is_zipfile(inner):
                            with zipfile.ZipFile(inner) as z2:
                                for i2 in z2.infolist():
                                    n2 = safe_name(i2.filename)
                                    if i2.is_dir() or not n2 or JUNK.search(n2) or _is_symlink(i2):
                                        continue
                                    with z2.open(i2) as src:
                                        _copy_into(zout, prefix + n2, src, budget)
                                    n += 1
                        elif name.lower().endswith(".7z"):
                            n += _sevenzip_into(inner, zout, prefix, budget, work)
                        else:
                            n += _tar_into(inner, zout, prefix, budget)
                        inner.unlink(missing_ok=True)
                    else:
                        with zin.open(info) as src:
                            _copy_into(zout, name, src, budget)
                        n += 1
    shutil.rmtree(work / "_inner", ignore_errors=True)
    if not n:
        raise FetchError(f"{path.name} contains no files.", "not_data")
    if log:
        log(f"Repacked {n:,} file(s) from {path.name} ({limits.human(budget.written)})")
    return out


def has_inner_archives(members: list[dict]) -> bool:
    return any(_NESTED.search(m["name"]) for m in members)
