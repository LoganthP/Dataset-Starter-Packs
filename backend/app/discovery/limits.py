"""Transfer and extraction budgets, in one place, so the UI, API, upload handling and workers agree.

  DSP_MAX_TRANSFER_BYTES   bytes moved over the network or uploaded: uploads, provider downloads, ZIPs
                           (default 2,000,000,000 = 2 GB). DSP_MAX_IMPORT_MB is still read as a fallback.
  DSP_MAX_EXTRACT_BYTES    bytes written when expanding archives for one run (default 6,000,000,000).
  DSP_MAX_ARCHIVE_MEMBERS  entries an archive may list (default 250,000).
  DSP_SAMPLE_MAX_MB        whole-file formats a Quick sample may download (default 25 MB).

Transferred bytes and expanded bytes are measured separately: a 185 MB ZIP that expands to 900 MB passes
the transfer limit and is then checked against the extraction budget.
"""
from __future__ import annotations

import os


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    try:
        return int(float(raw)) if raw else default
    except ValueError:
        return default


def _transfer_default() -> int:
    legacy = os.getenv("DSP_MAX_IMPORT_MB")  # older deployments set the limit in MiB
    return int(float(legacy) * 2**20) if legacy else 2_000_000_000


MAX_TRANSFER_BYTES = _int_env("DSP_MAX_TRANSFER_BYTES", _transfer_default())
MAX_EXTRACT_BYTES = _int_env("DSP_MAX_EXTRACT_BYTES", 6_000_000_000)
MAX_ARCHIVE_MEMBERS = _int_env("DSP_MAX_ARCHIVE_MEMBERS", 250_000)
QUICK_MAX_BYTES = int(float(os.getenv("DSP_SAMPLE_MAX_MB", "25")) * 2**20)
DOWNLOAD_RETRIES = _int_env("DSP_DOWNLOAD_RETRIES", 2)

LIMIT_NAMES = {
    "transfer": ("transfer limit", "DSP_MAX_TRANSFER_BYTES"),
    "extract": ("archive extraction budget", "DSP_MAX_EXTRACT_BYTES"),
    "members": ("archive entry limit", "DSP_MAX_ARCHIVE_MEMBERS"),
    "quick_sample": ("Quick sample budget", "DSP_SAMPLE_MAX_MB"),
    "staging": ("paged staging budget", "DSP_SODA_FULL_MAX_MB"),
}


def human(n: int | float | None) -> str:
    """Decimal units, matching how providers and file managers report sizes (2 GB = 2,000,000,000 bytes)."""
    if n is None:
        return "an unknown size"
    n = float(n)
    for unit in ("bytes", "KB", "MB", "GB", "TB"):
        if n < 1000 or unit == "TB":
            return f"{n:,.0f} {unit}" if unit == "bytes" else f"{n:,.1f} {unit}"
        n /= 1000
    return f"{n:,.1f} TB"


def detail(limit: str, measured: int | None, *, estimated: bool = False, actions: list[str] | None = None, **extra) -> dict:
    """Structured payload for a limit failure: which limit, its value, the measured or estimated size, next actions.

    actions: run_sample | prepare_archive_sample | full | date_range | upload | open_source | select_member
    """
    value = extra.pop("limit_value", None) or {"transfer": MAX_TRANSFER_BYTES, "extract": MAX_EXTRACT_BYTES, "members": MAX_ARCHIVE_MEMBERS,
                                                "quick_sample": QUICK_MAX_BYTES}.get(limit)
    label, env = LIMIT_NAMES.get(limit, (limit, ""))
    return {"limit": limit, "limitLabel": label, "limitEnv": env, "limitBytes": value, "measuredBytes": measured,
            "estimated": estimated, "actions": actions or [], **extra}


def capabilities() -> dict:
    return {"maxTransferBytes": MAX_TRANSFER_BYTES, "maxExtractBytes": MAX_EXTRACT_BYTES, "quickSampleBytes": QUICK_MAX_BYTES,
            "maxUploadMB": round(MAX_TRANSFER_BYTES / 2**20)}
