"""Vercel Blob support for large uploads on Vercel, where a function request body is capped at 4.5 MB.

The browser uploads the file straight to Blob with `@vercel/blob/client`'s `upload()`; this module issues
the short-lived client token that `upload()` asks for (the same token format and HMAC signature as
`generateClientTokenFromReadWriteToken` in @vercel/blob 2.x), reads the private blob server-side for
analysis, and deletes it afterwards. Needs BLOB_READ_WRITE_TOKEN (set when a Blob store is connected).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import urllib.request

API_URL = os.getenv("VERCEL_BLOB_API_URL", "https://vercel.com/api/blob")
API_VERSION = "13"
TOKEN_TTL_SECONDS = 3600


def token() -> str:
    return os.getenv("BLOB_READ_WRITE_TOKEN", "")


def enabled() -> bool:
    return bool(token())


def store_id(rw_token: str) -> str:
    parts = rw_token.split("_")
    return parts[3] if len(parts) > 3 else ""


def client_token(pathname: str, *, maximum_size_in_bytes: int, valid_until_ms: int | None = None, rw_token: str | None = None) -> str:
    rw = rw_token or token()
    sid = store_id(rw)
    if not sid:
        raise ValueError("BLOB_READ_WRITE_TOKEN is missing or invalid")
    # Same keys in the same order as generateClientTokenFromReadWriteToken (@vercel/blob 2.9), so tokens are byte-identical
    # to the official library's (tests/test_blob_token.py pins a value produced by it).
    payload = {"pathname": pathname, "maximumSizeInBytes": maximum_size_in_bytes,
               "validUntil": valid_until_ms or int((time.time() + TOKEN_TTL_SECONDS) * 1000), "addRandomSuffix": True}
    encoded = base64.b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()
    signature = hmac.new(rw.encode(), encoded.encode(), hashlib.sha256).hexdigest()
    return f"vercel_blob_client_{sid}_" + base64.b64encode(f"{signature}.{encoded}".encode()).decode()


def is_blob_url(url: str) -> bool:
    host = url.split("/")[2].split(":")[0].lower() if url.startswith("https://") else ""
    sid = store_id(token()).lower()
    return host.endswith(".blob.vercel-storage.com") and (not sid or host.split(".")[0] == sid)


def auth_headers() -> dict:
    return {"Authorization": f"Bearer {token()}"} if token() else {}


def delete(url: str) -> None:
    """Best effort: the analysis report keeps everything we need, so the uploaded file is removed."""
    if not enabled():
        return
    req = urllib.request.Request(f"{API_URL}/delete", data=json.dumps({"urls": [url]}).encode(), method="POST",
                                 headers={**auth_headers(), "content-type": "application/json", "x-api-version": API_VERSION})
    try:
        urllib.request.urlopen(req, timeout=15).close()
    except OSError:
        pass


def status() -> dict:
    """What is safe to show anyone: whether a store is configured and whether the token looks well-formed. No secrets."""
    rw = token()
    ok = bool(store_id(rw)) and rw.startswith("vercel_blob_rw_")
    return {"configured": bool(rw), "tokenFormatOk": ok if rw else None, "storeId": store_id(rw) or None if ok else None}


def check_remote(timeout: float = 8.0) -> dict:
    """Ask Blob whether this token works (a one-item list). Classifies the failure so the fix is obvious. No secrets returned."""
    import urllib.error

    if not enabled():
        return {"ok": False, "cause": "not_configured", "message": "BLOB_READ_WRITE_TOKEN is not set on this process."}
    if not status()["tokenFormatOk"]:
        return {"ok": False, "cause": "bad_token", "message": "BLOB_READ_WRITE_TOKEN is not a read/write token (it should start with vercel_blob_rw_)."}
    req = urllib.request.Request(f"{API_URL}/?limit=1", headers={**auth_headers(), "x-api-version": API_VERSION,
                                                                  "x-vercel-blob-store-id": store_id(token())})
    try:
        urllib.request.urlopen(req, timeout=timeout).close()
        return {"ok": True, "cause": None, "message": "The Blob store accepted this process's token."}
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            return {"ok": False, "cause": "token_rejected", "message": "Blob rejected the token (revoked, from another store, or the store was deleted). "
                                                                       "Reconnect the store and set the same BLOB_READ_WRITE_TOKEN on Vercel and the worker."}
        if exc.code == 429:
            return {"ok": False, "cause": "rate_limited", "message": "Blob is rate limiting this store; retry shortly."}
        if exc.code == 402:
            return {"ok": False, "cause": "quota", "message": "The Blob store is over its plan's quota or the account needs billing attention."}
        return {"ok": False, "cause": "provider_error", "message": f"Blob answered HTTP {exc.code}."}
    except OSError as exc:
        return {"ok": False, "cause": "network", "message": f"Could not reach Blob: {exc.__class__.__name__}."}


class BlobProblem(Exception):
    """A definite, explainable reason an uploaded file can't be used. kind matches the analysis error kinds."""

    def __init__(self, message: str, kind: str, size: int | None = None):
        super().__init__(message)
        self.kind, self.size = kind, size


def probe(url: str, timeout: float = 10.0) -> int | None:
    """Check from the API that the uploaded file is there and readable with this app's token. Returns its size in bytes
    (None if Blob can't be reached right now: the worker will find out). Raises BlobProblem for a definite answer."""
    import urllib.error

    req = urllib.request.Request(url, headers={**auth_headers(), "Range": "bytes=0-0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            rng = r.headers.get("Content-Range", "")
            total = int(rng.rsplit("/", 1)[1]) if "/" in rng and rng.rsplit("/", 1)[1].isdigit() else int(r.headers.get("Content-Length") or 0)
            return total or None
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise BlobProblem(f"The app's Blob token can't read this upload (HTTP {exc.code}). BLOB_READ_WRITE_TOKEN on Vercel must belong to the store "
                              "the file was uploaded to; the worker needs the same value.", "auth") from exc
        if exc.code in (404, 410):
            raise BlobProblem("The uploaded file isn't in Blob (the upload didn't finish, or it was deleted). Upload it again.", "not_found") from exc
        if exc.code == 416:  # empty object
            raise BlobProblem("The uploaded file is empty.", "not_data") from exc
        return None
    except (OSError, ValueError):
        return None
