"""Shared HTTP helper for provider adapters: timeouts, a user agent and readable errors."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

TIMEOUT = float(os.getenv("DSP_ADAPTER_TIMEOUT_SECONDS", "20"))


class AdapterError(RuntimeError):
    pass


def get_json(url: str, headers: dict | None = None, timeout: float | None = None):
    req = urllib.request.Request(url, headers={"User-Agent": "dataset-starter-packs/0.2 discovery", "Accept": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout or TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise AdapterError(f"HTTP {exc.code} from {url.split('?')[0]}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise AdapterError(f"{type(exc).__name__}: {getattr(exc, 'reason', exc)}") from exc
    except json.JSONDecodeError as exc:
        raise AdapterError(f"Response from {url.split('?')[0]} was not JSON") from exc


def get_text(url: str, limit: int = 1_500_000, headers: dict | None = None, timeout: float | None = None) -> tuple[str, str]:
    """GET a page (following redirects). Returns (final_url, text) reading at most `limit` bytes."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; dataset-starter-packs/0.5)", "Accept": "text/html,*/*",
                                               **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout or TIMEOUT) as resp:
            return resp.geturl(), resp.read(limit).decode(resp.headers.get_content_charset() or "utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raise AdapterError(f"HTTP {exc.code} from {url.split('?')[0]}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise AdapterError(f"{type(exc).__name__}: {getattr(exc, 'reason', exc)}") from exc


def get_json_with_headers(url: str, headers: dict | None = None, timeout: float | None = None):
    """(data, response headers) for paginated APIs that use Link headers (Hugging Face tree listing)."""
    req = urllib.request.Request(url, headers={"User-Agent": "dataset-starter-packs/0.7 discovery", "Accept": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout or TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8")), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        raise AdapterError(f"HTTP {exc.code} from {url.split('?')[0]}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise AdapterError(f"{type(exc).__name__}: {getattr(exc, 'reason', exc)}") from exc
    except json.JSONDecodeError as exc:
        raise AdapterError(f"Response from {url.split('?')[0]} was not JSON") from exc
