"""Bounded file access for Analyze: check a file before a job starts, then download it with deadlines.

probe()     One small ranged GET (first 8 KB). Catches what used to surface only after a long download:
            sign-in / terms walls (401/403, or an HTML page where a data file should be), missing files,
            unsupported archives (7z, RAR), and files too large for the chosen mode.
download()  Streams to disk with three limits: connect + idle timeout (no bytes for `idle` seconds),
            an overall deadline, and a byte cap. With `stop_after_lines` it stops early, after the header
            plus N rows, so a "sample" of a huge CSV costs one small read instead of the full export.
"""
from __future__ import annotations

import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .dataimport import ImportError_

UA = "dataset-starter-packs/0.6"


class FetchError(ImportError_):
    """kind: auth | consent | not_found | not_data | format | too_large | timeout | network | cancelled
    detail: optional structured payload (limits.detail(): which limit, measured size, next actions)."""

    def __init__(self, message: str, kind: str, detail: dict | None = None):
        super().__init__(message)
        self.kind = kind
        self.detail = detail


RETRYABLE = ("timeout", "network")


def headers_for(url: str, auth: dict | None = None) -> dict:
    """Request headers for a file URL. `auth` carries per-user credentials (a connected Kaggle account)
    and wins over server-wide ones. Credentials only ever go in headers, never in URLs or logs."""
    from .. import kaggle_connect

    h = {"User-Agent": UA}
    if kaggle_connect.is_kaggle_url(url):
        if auth:
            h.update(auth)
        else:
            from .adapters.kaggle import _auth_header

            h.update(_auth_header())
    from .. import blob

    if blob.is_blob_url(url):
        h.update(blob.auth_headers())
    return h


def _http_error(exc: urllib.error.HTTPError, host: str) -> FetchError:
    from .. import kaggle_connect

    if host.endswith(".blob.vercel-storage.com"):
        if exc.code in (401, 403):
            return FetchError(f"Blob refused to give this upload to the analysis worker (HTTP {exc.code}). The worker's BLOB_READ_WRITE_TOKEN "
                              "must be the token of the same Blob store the app uploads to. Set it on the worker, restart it, and run again.", "auth")
        if exc.code in (404, 410):
            return FetchError("The uploaded file is no longer in Blob (deleted, or the upload never finished). Upload it again.", "not_found")

    if host.endswith(".blob.vercel-storage.com"):
        if exc.code == 413:
            return FetchError("The Blob upload exceeded the provider transfer limit (HTTP 413).", "too_large")
        if exc.code == 429:
            return FetchError("Vercel Blob rate limit or quota exceeded (HTTP 429). Try again later.", "network")

    if kaggle_connect.is_kaggle_url(f"https://{host}/") and exc.code == 403:
        body = ""
        try:
            body = exc.read(2000).decode("utf-8", "replace").lower()
        except Exception:  # noqa: BLE001
            pass
        if any(w in body for w in ("accept", "rules", "terms", "consent")):
            return FetchError("Kaggle needs you to accept this dataset's terms before it can be downloaded. Open the dataset on Kaggle, "
                              "accept, then come back and retry.", "consent")
    if exc.code in (401, 403, 407):
        return FetchError(f"{host} refused the download (HTTP {exc.code}). It needs you to sign in or accept the dataset's terms. "
                          "Open the source, download the file in your browser, then upload it here.", "auth")
    if exc.code in (404, 410):
        return FetchError(f"{host} no longer serves this file (HTTP {exc.code}). Check the source for a newer link.", "not_found")
    if exc.code == 429:
        return FetchError(f"{host} is rate-limiting downloads (HTTP 429). Try again in a few minutes.", "network")
    return FetchError(f"{host} returned HTTP {exc.code}.", "network")


def _looks_like_html(head: bytes, ctype: str) -> bool:
    start = head.lstrip()[:200].lower()
    return "text/html" in ctype or start.startswith((b"<!doctype html", b"<html", b"<head"))


def sniff(head: bytes) -> str:
    """File type from its first bytes (signature first, then structure), not its extension."""
    from .formats.registry import sniff as _sniff

    return _sniff(head)


def probe(url: str, expect: str | None, timeout: float = 12.0, auth: dict | None = None) -> dict:
    """Read the first 8 KB. Returns {bytes_total, content_type, kind, ranges} or raises FetchError."""
    host = urllib.parse.urlparse(url).netloc or url
    req = urllib.request.Request(url, headers={**headers_for(url, auth), "Range": "bytes=0-8191"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            head = resp.read(8192)
            ctype = (resp.headers.get("Content-Type") or "").lower()
            final = resp.geturl()
            total = None
            ranges = resp.status == 206
            etag = resp.headers.get("ETag")
            last_modified = resp.headers.get("Last-Modified")
            if cr := resp.headers.get("Content-Range"):  # bytes 0-8191/123456
                tail = cr.rsplit("/", 1)[-1]
                total = int(tail) if tail.isdigit() else None
            elif resp.status == 200 and resp.headers.get("Content-Length", "").isdigit():
                total = int(resp.headers["Content-Length"])
    except urllib.error.HTTPError as exc:
        if exc.code == 416:  # empty file or ranges unsupported oddly
            raise FetchError(f"{host} returned an empty file.", "not_data") from exc
        raise _http_error(exc, host) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise FetchError(f"Couldn't reach {host}: {getattr(exc, 'reason', exc)}.", "network") from exc

    if _looks_like_html(head, ctype):
        login = any(w in final.lower() for w in ("login", "signin", "sign-in", "account", "auth", "consent"))
        raise FetchError(f"{host} answered with a web page instead of the data file"
                         f"{' (a sign-in page)' if login else ''}. It probably needs sign-in or accepting terms: "
                         "open the source, download the file, then upload it here.", "auth")
    if head.startswith(b"Rar!"):
        raise FetchError("This is a RAR archive, which can't be opened here. Extract it and upload the data files, or a ZIP of them.", "format")
    if head.startswith(b"7z\xbc\xaf"):
        import importlib.util

        if importlib.util.find_spec("py7zr") is None:
            raise FetchError("This is a 7-Zip archive; this deployment can't open those (the Docker worker can). Extract it and upload "
                             "the data files, or a ZIP of them.", "format")
    detected = sniff(head)
    kind = {"parquet": "parquet", "zip": "zip", "gzip": "gzip"}.get(detected, "text" if detected in ("csv", "tsv", "json", "sinex", "text")
                                                                     else "binary")
    if expect == "parquet" and kind != "parquet":
        raise FetchError("The file isn't valid Parquet (no PAR1 header).", "format")
    if expect in ("csv", "tsv", "json") and kind == "binary":
        raise FetchError(f"The file looks binary ({detected}), not {expect.upper()}.", "format")
    return {"bytes_total": total, "content_type": ctype, "kind": kind, "detected": detected, "ranges": ranges, "etag": etag,
            "last_modified": last_modified, "final_url": final}


def download(url: str, dest: Path, *, max_bytes: int, deadline: float, idle: float, stop_after_lines: int | None = None,
             progress=None, auth: dict | None = None, retries: int = 0, limit_name: str = "transfer") -> dict:
    """Stream url -> dest. `deadline` is a time.monotonic() value. Returns {bytes, truncated, bytes_total}.

    retries: temporary failures (timeouts, connection resets, HTTP 5xx/429) are retried this many times with
    backoff. When the server honours Range, the retry resumes after the bytes already on disk."""
    attempt = 0
    while True:
        try:
            return _download_once(url, dest, max_bytes=max_bytes, deadline=deadline, idle=idle, stop_after_lines=stop_after_lines,
                                  progress=progress, auth=auth, resume=attempt > 0 and stop_after_lines is None, limit_name=limit_name)
        except FetchError as exc:
            attempt += 1
            if exc.kind not in RETRYABLE or attempt > retries or time.monotonic() + 2 * attempt > deadline:
                raise
            time.sleep(min(2.0 * attempt, 8.0))


def _limit_error(size: int, max_bytes: int, *, estimated: bool, limit_name: str) -> FetchError:
    from . import limits

    what = "is" if not estimated else "reports"
    if limit_name == "quick_sample":
        return FetchError(f"The file {what} {limits.human(size)}, more than a Quick sample downloads ({limits.human(max_bytes)}).", "too_large",
                          limits.detail("quick_sample", size, estimated=estimated, actions=["prepare_archive_sample", "full"], limit_value=max_bytes))
    return FetchError(f"The file {what} {limits.human(size)}, over the {limits.human(max_bytes)} transfer limit (DSP_MAX_TRANSFER_BYTES). "
                      "Nothing more was downloaded.", "too_large",
                      limits.detail("transfer", size, estimated=estimated, actions=["run_sample", "date_range", "open_source"], limit_value=max_bytes))


def _download_once(url: str, dest: Path, *, max_bytes: int, deadline: float, idle: float, stop_after_lines: int | None,
                   progress, auth: dict | None, resume: bool, limit_name: str) -> dict:
    host = urllib.parse.urlparse(url).netloc or url
    have = dest.stat().st_size if resume and dest.exists() else 0
    headers = headers_for(url, auth)
    if have:
        headers["Range"] = f"bytes={have}-"
    req = urllib.request.Request(url, headers=headers)
    size, lines, truncated, last_report = 0, 0, False, 0.0
    try:
        with urllib.request.urlopen(req, timeout=idle) as resp:
            resumed = bool(have) and resp.status == 206
            mode = "ab" if resumed else "wb"
            size = have if resumed else 0
            declared = int(resp.headers.get("Content-Length") or 0) or None
            if declared is not None and resumed:
                declared += have
            if declared and declared > max_bytes and not stop_after_lines:
                raise _limit_error(declared, max_bytes, estimated=True, limit_name=limit_name)
            with open(dest, mode) as out:
                while True:
                    if time.monotonic() > deadline:
                        raise FetchError(f"Timed out downloading from {host} after {size / 1e6:,.1f} MB.", "timeout")
                    chunk = resp.read1(1 << 18)  # whatever has arrived, so the deadline is checked often
                    if not chunk:
                        break
                    if stop_after_lines is not None:
                        nl = chunk.count(b"\n")
                        if lines + nl >= stop_after_lines:  # keep exactly the first `stop_after_lines` lines
                            need, cut = stop_after_lines - lines, -1
                            for _ in range(need):
                                cut = chunk.index(b"\n", cut + 1)
                            out.write(chunk[: cut + 1])
                            size += cut + 1
                            truncated = True
                            break
                        lines += nl
                    if size + len(chunk) > max_bytes:
                        if stop_after_lines is not None:  # sample: keep whole lines up to the cap
                            part = chunk[: max_bytes - size]
                            part = part[: part.rfind(b"\n") + 1]
                            out.write(part)
                            size += len(part)
                            truncated = True
                            break
                        raise _limit_error(size + len(chunk), max_bytes, estimated=False, limit_name=limit_name)
                    out.write(chunk)
                    size += len(chunk)
                    now = time.monotonic()
                    if progress and now - last_report > 0.25:  # cancel is checked here too
                        progress(size, declared)
                        last_report = now
            if declared and not truncated and size < declared:
                raise FetchError(f"{host} closed the connection after {size / 1e6:,.1f} of {declared / 1e6:,.1f} MB.", "network")
            if progress:
                progress(size, declared)
    except FetchError:
        raise
    except urllib.error.HTTPError as exc:
        if exc.code == 416 and have:  # already complete
            return {"bytes": have, "truncated": False, "bytes_total": have}
        err = _http_error(exc, host)
        if exc.code >= 500:
            err.kind = "network"
        raise err from exc
    except TimeoutError as exc:
        raise FetchError(f"{host} stopped sending data for {idle:.0f} seconds after {size / 1e6:,.1f} MB.", "timeout") from exc
    except (urllib.error.URLError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        kind = "timeout" if "timed out" in str(reason).lower() else "network"
        raise FetchError(f"Download from {host} failed: {reason}.", kind) from exc
    return {"bytes": size, "truncated": truncated, "bytes_total": declared}
