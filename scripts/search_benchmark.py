"""Measure search quality on catalog/benchmark.json.

    python scripts/search_benchmark.py            # print the report; exit 1 on any hard-filter violation

Tracks: how often a suitable dataset is in the top five, and how often a requirement check lets a
non-qualifying record through as a confirmed match.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("DSP_STATE_DIR", tempfile.mkdtemp(prefix="dsp-bench-"))

from app.discovery import benchmark, store  # noqa: E402


def main() -> int:
    store.load_seeds()
    report = benchmark.run()
    for row in report["rows"]:
        mark = "hit " if row["hit"] else "MISS"
        print(f"{mark}  {row['id']:22} top5: {', '.join(row['top5']) or '-'}")
        for p in row["problems"]:
            print(f"      VIOLATION: {p}")
    print(f"\nTop-5 hit rate: {report['top5_hit_rate']:.0%} over {report['cases']} queries; hard-filter violations: {report['violations']}")
    return 1 if report["violations"] or report["top5_hit_rate"] < 1 else 0


if __name__ == "__main__":
    sys.exit(main())
