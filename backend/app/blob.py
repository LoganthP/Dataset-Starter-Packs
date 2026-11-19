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
    payload = {"pathname": pathname, "maximumSizeInBytes": maximum_size_in_bytes, "addRandomSuffix": True,
               "validUntil": valid_until_ms or int((time.time() + TOKEN_TTL_SECONDS) * 1000)}
    encoded = base64.b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()
    signature = hmac.new(rw.encode(), encoded.encode(), hashlib.sha256).hexdigest()
    return f"vercel_blob_client_{sid}_" + base64.b64encode(f"{signature}.{encoded}".encode()).decode()


def is_blob_url(url: str) -> bool:
    host = url.split("/")[2] if url.startswith("https://") else ""
    return host.endswith(".blob.vercel-storage.com") and (not store_id(token()) or host.split(".")[0] == store_id(token()).lower())


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
