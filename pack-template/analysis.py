"""Analysis template: python analysis.py --mode sample --out outputs/sample

Writes results.json with the shape the web app renders:
headline, metrics[], tables[], charts[], checks[] (the trap!), notes[], provenance.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

import load_data

PACK = "provider-short-name"  # TODO


def run(mode: str = "sample", out_dir: str | Path = "outputs/sample", params: dict | None = None) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    print("[1/3] Loading", flush=True)
    df = load_data.load(mode)
    print("[2/3] Baseline", flush=True)
    baseline = float(df["target"].mean())  # TODO: a real baseline
    print("[3/3] Writing results", flush=True)
    results = {
        "pack": PACK, "mode": mode, "is_sample": mode == "sample",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "headline": f"Baseline: {baseline:.2f}",
        "metrics": [{"key": "baseline", "label": "Baseline", "value": baseline, "unit": "", "better": None, "hint": ""}],
        "tables": [], "charts": [],
        "checks": [{"name": "TODO: the pack's signature trap", "passed": True, "detail": ""}],
        "notes": [], "provenance": load_data.provenance(mode),
    }
    (out / "results.json").write_text(json.dumps(results, indent=2))
    print(f"Done: {results['headline']}", flush=True)
    return results


if __name__ == "__main__":
    import matplotlib

    matplotlib.use("Agg")
    p = argparse.ArgumentParser()
    p.add_argument("--mode", default="sample", choices=["sample", "real"])
    p.add_argument("--out", default=None)
    p.add_argument("--param", action="append", default=[])
    a = p.parse_args()
    run(a.mode, a.out or f"outputs/{a.mode}", dict(x.split("=", 1) for x in a.param))
