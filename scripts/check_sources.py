"""Scheduled source check: do official links respond and do small API queries return expected fields?

Writes a Markdown report to $GITHUB_STEP_SUMMARY when run in Actions. Never fails the build
for an upstream outage (exit code 0) unless --strict is passed.

    python scripts/check_sources.py [--strict]
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def probe(url: str, expect: list[str] | None = None) -> tuple[bool, str]:
    started = time.monotonic()
    req = urllib.request.Request(url, headers={"User-Agent": "dataset-starter-packs/0.1 source-check"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read(400_000).decode("utf-8", "replace")
            ms = int((time.monotonic() - started) * 1000)
            missing = [t for t in (expect or []) if t not in body]
            return (not missing, f"HTTP {r.status}, {ms} ms" + (f", missing fields: {missing}" if missing else ""))
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}"
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"


def main() -> int:
    strict = "--strict" in sys.argv
    lines = ["## Source check", "", "| Pack | Check | Result | Detail |", "|---|---|---|---|"]
    failures = 0
    for meta_path in sorted((ROOT / "packs").glob("*/pack.json")):
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        src = meta["source"]
        checks = []
        if src.get("health_check_url"):
            checks.append(("API query", src["health_check_url"], src.get("health_check_expect")))
        checks.append(("dataset page", src["dataset_page"], None))
        for kind, url, expect in checks:
            ok, detail = probe(url, expect)
            if src["access_method"] == "kaggle" and kind == "dataset page" and not ok:
                status = "manual"
                detail += " - Kaggle blocks scripted requests; verify in a browser"
            else:
                status = "ok" if ok else "FAIL"
                failures += not ok
            lines.append(f"| {meta['slug']} | {kind} | {status} | {detail} |")
            print(f"{meta['slug']:28} {kind:13} {status:6} {detail}")
    report = "\n".join(lines)
    if os.getenv("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(report + "\n")
    return 1 if strict and failures else 0


if __name__ == "__main__":
    sys.exit(main())
