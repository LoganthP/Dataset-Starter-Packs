"""Format registry. Each handler declares what it reads and how sure it is; Run never needs to change
when a format is added.

    class MyHandler(Handler):
        key = "netcdf"; label = "NetCDF"; types = ("netcdf",)
        def analyze(self, job): ...           # returns a report dict (see Job)

    register(MyHandler())

Detection uses file signatures and structure first (sniff), then extensions (type_from_name).
For archives, plan() scores every handler against the member list and picks the best match; the user
can override it by choosing members (params.members) or a handler (params.handler).
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

TABULAR = ("csv", "tsv", "json", "parquet", "xlsx")
# Read by converting to a table first (formats/convert.py): spreadsheets, statistics packages, scientific arrays, XML records.
CONVERTED = ("xls", "ods", "stata", "sas", "spss", "netcdf", "hdf5", "xmltable")
IMAGE = ("png", "jpeg", "tiff", "bmp", "webp")
ANNOTATION = ("coco", "yolo", "dota", "voc", "labelme", "txt", "json", "xml", "yaml")

_EXT = [(".snx.gz", "sinex-gz"), (".sinex.gz", "sinex-gz"), (".snx.z", "sinex-z"), (".snx", "sinex"), (".sinex", "sinex"),
        (".parquet", "parquet"), (".pq", "parquet"), (".csv.gz", "csv"), (".csv", "csv"), (".tsv", "tsv"), (".tab", "tsv"), (".jsonl", "json"),
        (".ndjson", "json"), (".geojson", "json"), (".json", "json"), (".xlsx", "xlsx"), (".xlsm", "xlsx"), (".xls", "xls"), (".ods", "ods"),
        (".dta", "stata"), (".sas7bdat", "sas"), (".xpt", "sas"), (".sav", "spss"), (".zsav", "spss"),
        (".tar.gz", "tar"), (".tgz", "tar"), (".tar.bz2", "tar"), (".tbz2", "tar"), (".tar.xz", "tar"), (".txz", "tar"), (".tar", "tar"),
        (".zip", "zip"), (".png", "png"), (".jpg", "jpeg"), (".jpeg", "jpeg"), (".tif", "tiff"), (".tiff", "tiff"), (".bmp", "bmp"),
        (".webp", "webp"), (".xml", "xml"), (".txt", "txt"), (".yaml", "yaml"), (".yml", "yaml"), (".nc", "netcdf"), (".nc4", "netcdf"),
        (".cdf", "netcdf"), (".h5", "hdf5"), (".hdf5", "hdf5"), (".he5", "hdf5"), (".gz", "gzip"), (".bz2", "bzip2"), (".xz", "xz"),
        (".z", "compress"), (".7z", "7z"), (".rar", "rar"), (".pdf", "pdf"), (".md", "text")]


def type_from_name(name: str) -> str:
    n = name.lower().split("?")[0]
    for ext, t in _EXT:
        if n.endswith(ext):
            return t
    return "unknown"


def sniff(head: bytes, name: str = "") -> str:
    """Type from content: signatures first, then text structure; the name only breaks ties."""
    h = head
    sigs = [(b"PAR1", "parquet"), (b"PK\x03\x04", "zip"), (b"PK\x05\x06", "zip"), (b"\x1f\x8b", "gzip"), (b"\x1f\x9d", "compress"),
            (b"\x89PNG\r\n\x1a\n", "png"), (b"\xff\xd8\xff", "jpeg"), (b"II*\x00", "tiff"), (b"MM\x00*", "tiff"), (b"BM", "bmp"),
            (b"CDF\x01", "netcdf"), (b"CDF\x02", "netcdf"), (b"\x89HDF\r\n\x1a\n", "hdf5"), (b"7z\xbc\xaf", "7z"), (b"Rar!", "rar"),
            (b"%PDF", "pdf"), (b"RIFF", "webp"), (b"BZh", "bzip2"), (b"\xfd7zXZ\x00", "xz"), (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "ole"),
            (b"$FL2", "spss"), (b"$FL3", "spss"), (b"<stata_dta>", "stata"),
            (b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xc2\xea\x81\x60\xb3\x14\x11\xcf\xbd\x92\x08\x00\x09\xc7\x31\x8c\x18\x1f\x10\x11", "sas")]
    for sig, t in sigs:
        if h.startswith(sig):
            if t == "gzip" and ".snx" in name.lower():
                return "sinex-gz"
            if t == "gzip" and type_from_name(name) == "tar":
                return "tar"
            if t in ("bzip2", "xz") and type_from_name(name) == "tar":
                return "tar"
            if t == "ole":  # Excel 97-2003 (and other old Office files)
                return "xls" if type_from_name(name) in ("xls", "unknown") else type_from_name(name)
            if t == "hdf5" and type_from_name(name) == "netcdf":
                return "netcdf"  # NetCDF-4 is HDF5 inside
            return t
    if len(h) > 262 and h[257:262] == b"ustar":
        return "tar"
    text = h.lstrip(b"\xef\xbb\xbf")
    if b"\x00" in text[:4096]:
        return "binary"
    first = text.lstrip()[:200]
    if text.startswith(b"%=SNX") or b"+SOLUTION/ESTIMATE" in text or b"+SITE/ID" in text:
        return "sinex"
    if first.startswith((b"<!doctype html", b"<html", b"<head", b"<!DOCTYPE html")):
        return "html"
    if first.startswith((b"{", b"[")):
        return "json"
    if first.startswith(b"<?xml") or first.startswith(b"<annotation"):
        return "xml"
    lines = [ln for ln in text.splitlines()[:20] if ln.strip()]
    if len(lines) > 1 and text.splitlines()[-1:] and len(lines) > 2:
        lines = lines[:-1]  # the 8 KB window usually cuts the last line
    if lines:
        for delim, kind in ((b"\t", "tsv"), (b",", "csv"), (b";", "csv"), (b"|", "csv")):
            counts = [ln.count(delim) for ln in lines[:15]]
            if min(counts) >= 1 and len(set(counts)) <= 2:
                return kind
    t = type_from_name(name)
    return t if t != "unknown" else "text"


def sniff_path(path: Path) -> str:
    with open(path, "rb") as fh:
        t = sniff(fh.read(8192), path.name)
    if t == "zip":  # Excel and OpenDocument files are ZIP containers: look inside before treating them as archives
        import zipfile

        try:
            with zipfile.ZipFile(path) as zf:
                names = set(zf.namelist())
                if "xl/workbook.xml" in names:
                    return "xlsx"
                if "mimetype" in names and zf.read("mimetype").startswith(b"application/vnd.oasis.opendocument.spreadsheet"):
                    return "ods"
        except (zipfile.BadZipFile, OSError, KeyError):
            pass
    if t in ("gzip", "bzip2", "xz") and type_from_name(path.name) != "tar":  # a compressed tar without .tar in its name
        import bz2
        import gzip
        import lzma

        opener = {"gzip": gzip.open, "bzip2": bz2.open, "xz": lzma.open}[t]
        try:
            with opener(path, "rb") as fh:
                head = fh.read(512)
            if len(head) > 262 and head[257:262] == b"ustar":
                return "tar"
        except (OSError, EOFError, lzma.LZMAError):
            pass
    return t


@dataclass
class Job:
    """What a handler gets. `paths` are local files (already downloaded and extracted)."""

    paths: list[Path]
    root: Path
    sample: bool
    deadline: float
    params: dict = field(default_factory=dict)
    members: list[dict] = field(default_factory=list)  # the whole archive listing, when the input was an archive
    progress: Callable[[str, int, int | None, str], None] = lambda phase, done, total, unit: None
    cancel: Callable[[], None] = lambda: None
    log: Callable[[str], None] = lambda line: None
    on_charts: Callable[[], None] | None = None
    known_total: int | None = None
    partial: bool = False
    method: str | None = None
    extra: dict = field(default_factory=dict)


class Handler:
    key = "base"
    label = "Base"
    types: tuple[str, ...] = ()
    description = ""

    def score(self, members: list[dict]) -> float:
        """0..1: how well this handler fits an archive listing (or a single file wrapped as one member)."""
        if not members:
            return 0.0
        hits = sum(1 for m in members if m["type"] in self.types)
        return hits / len(members) if hits else 0.0

    def select(self, members: list[dict], *, sample: bool, params: dict) -> list[dict]:
        """The members this handler needs from an archive (only these are extracted)."""
        return [m for m in members if m["type"] in self.types]

    def analyze(self, job: Job) -> dict:  # pragma: no cover - interface
        raise NotImplementedError


_REGISTRY: list[Handler] = []


def register(handler: Handler) -> Handler:
    _REGISTRY[:] = [h for h in _REGISTRY if h.key != handler.key] + [handler]
    return handler


def handlers() -> list[Handler]:
    _load()
    return list(_REGISTRY)


def get(key: str) -> Handler | None:
    return next((h for h in handlers() if h.key == key), None)


_BUILTIN = ("images", "inspect", "sinex", "tabular")


def _load() -> None:
    """Import the built-in handlers (each registers itself). Idempotent; extra handlers register on import."""
    import importlib

    for name in _BUILTIN:
        importlib.import_module(f"{__package__}.{name}")


def plan(members: list[dict], *, sample: bool, params: dict | None = None) -> dict:
    """Pick the handler and the members to extract. {handler, selected, scores, candidates}."""
    params = params or {}
    hs = handlers()
    chosen_names = set(params.get("members") or [])
    pool = [m for m in members if m["name"] in chosen_names] if chosen_names else members
    scores = {h.key: round(h.score(pool), 3) for h in hs}
    forced = get(params["handler"]) if params.get("handler") else None
    best = forced or max((h for h in hs if h.key != "inspect"), key=lambda h: scores[h.key], default=None)
    if best is None or (not forced and scores.get(best.key, 0) == 0):
        best = get("inspect")
    selected = best.select(pool, sample=sample, params=params)
    if not selected and best.key != "inspect":
        best, selected = get("inspect"), []
    return {"handler": best, "selected": selected, "scores": scores}


def describe(members: list[dict]) -> dict:
    """Counts by detected type, used by inspection reports and the member picker."""
    by: dict[str, dict] = {}
    for m in members:
        d = by.setdefault(m["type"], {"type": m["type"], "files": 0, "bytes": 0})
        d["files"] += 1
        d["bytes"] += m.get("size") or 0
    return {"types": sorted(by.values(), key=lambda d: -d["files"])}


def stem_key(name: str) -> str:
    """Join key between an image and its annotation file: the file name without folders and extension."""
    base = name.rsplit("/", 1)[-1]
    return re.sub(r"\.[A-Za-z0-9]+$", "", base).lower()
