"""Exoplanet discovery methods over time, radius vs. orbital period, and detection bias.

    python analysis.py --mode sample
    python analysis.py --mode real
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

import numpy as np
import pandas as pd

import load_data

PACK = "nasa-exoplanets"
METHOD_COLORS = {
    "Transit": "#6366F1",
    "Radial Velocity": "#F97316",
    "Microlensing": "#14B8A6",
    "Imaging": "#EC4899",
    "Transit Timing Variations": "#EAB308",
    "Other": "#94A3B8",
}
TOP_METHODS = list(METHOD_COLORS)[:-1]


def group_method(series: pd.Series) -> pd.Series:
    return series.where(series.isin(TOP_METHODS), "Other")


def missingness(catalog: pd.DataFrame) -> pd.DataFrame:
    """Missing-value report on the FULL catalog - computed before any filtering."""
    cols = ["pl_rade", "pl_orbper", "pl_bmasse", "sy_dist", "disc_year"]
    rep = pd.DataFrame({"missing": catalog[cols].isna().sum(), "total": len(catalog)})
    rep["missing_pct"] = (rep["missing"] / rep["total"] * 100).round(1)
    return rep


def radius_coverage_by_method(catalog: pd.DataFrame) -> pd.DataFrame:
    g = catalog.assign(method=group_method(catalog["discoverymethod"]))
    out = g.groupby("method").agg(planets=("pl_name", "count"),
                                  with_radius=("pl_rade", lambda s: int(s.notna().sum())),
                                  with_period=("pl_orbper", lambda s: int(s.notna().sum())))
    out["radius_pct"] = (out["with_radius"] / out["planets"] * 100).round(1)
    return out.sort_values("planets", ascending=False)


def scatter_frame(catalog: pd.DataFrame) -> pd.DataFrame:
    """Rows usable on the radius-period plot (both values present)."""
    return catalog.dropna(subset=["pl_rade", "pl_orbper"]).assign(method=lambda d: group_method(d["discoverymethod"]))


def method_baseline(catalog: pd.DataFrame, seed: int = 0) -> dict:
    """How well do period and radius alone reveal the discovery method? (Detection bias, quantified.)"""
    from sklearn.dummy import DummyClassifier
    from sklearn.metrics import f1_score
    from sklearn.model_selection import train_test_split
    from sklearn.tree import DecisionTreeClassifier

    d = scatter_frame(catalog)
    counts = d["method"].value_counts()
    d = d[d["method"].isin(counts[counts >= 6].index)]
    X = np.log10(d[["pl_orbper", "pl_rade"]].to_numpy())
    y = d["method"].to_numpy()
    X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.3, stratify=y, random_state=seed)
    dummy = DummyClassifier(strategy="most_frequent").fit(X_tr, y_tr)
    tree = DecisionTreeClassifier(max_depth=4, class_weight="balanced", random_state=seed).fit(X_tr, y_tr)
    return {
        "classes": sorted(set(y)),
        "majority_macro_f1": float(f1_score(y_te, dummy.predict(X_te), average="macro", zero_division=0)),
        "tree_macro_f1": float(f1_score(y_te, tree.predict(X_te), average="macro", zero_division=0)),
        "n_train": int(len(y_tr)),
        "n_test": int(len(y_te)),
    }


def _stamp(fig, is_sample):
    if is_sample:
        fig.text(0.99, 0.01, "SYNTHETIC SAMPLE - invented planets", ha="right", va="bottom", fontsize=8, color="#F97316")


def plot_discoveries(catalog: pd.DataFrame, out: Path, is_sample: bool) -> str:
    import matplotlib.pyplot as plt

    g = catalog.dropna(subset=["disc_year"]).assign(method=lambda d: group_method(d["discoverymethod"]))
    table = g.pivot_table(index="disc_year", columns="method", values="pl_name", aggfunc="count", fill_value=0)
    table = table[[m for m in METHOD_COLORS if m in table.columns]]
    fig, ax = plt.subplots(figsize=(10, 4.2))
    bottom = np.zeros(len(table))
    for m in table.columns:
        ax.bar(table.index, table[m], bottom=bottom, color=METHOD_COLORS[m], label=m, width=0.85)
        bottom += table[m].to_numpy()
    ax.set(xlabel="Discovery year", ylabel="Planets discovered", title="Confirmed exoplanet discoveries by method")
    ax.grid(alpha=0.25, axis="y")
    ax.legend(frameon=False, fontsize=8, ncol=2)
    _stamp(fig, is_sample)
    fig.tight_layout()
    fig.savefig(out / "discoveries_by_year.png", dpi=130)
    plt.close(fig)
    return "discoveries_by_year.png"


def plot_radius_period(catalog: pd.DataFrame, out: Path, is_sample: bool) -> str:
    import matplotlib.pyplot as plt

    d = scatter_frame(catalog)
    fig, ax = plt.subplots(figsize=(8, 5.5))
    for m in METHOD_COLORS:
        sub = d[d["method"] == m]
        if len(sub):
            ax.scatter(sub["pl_orbper"], sub["pl_rade"], s=10, alpha=0.65, color=METHOD_COLORS[m], label=f"{m} ({len(sub)})")
    ax.set(xscale="log", yscale="log", xlabel="Orbital period (days)", ylabel="Planet radius (Earth radii)",
           title=f"Radius vs. period - {len(d):,} of {len(catalog):,} planets have both values")
    for r, label in ((1, "Earth"), (11.2, "Jupiter")):
        ax.axhline(r, color="#CBD5E1", lw=1, ls=":")
        ax.text(ax.get_xlim()[0] * 1.2 if ax.get_xlim()[0] > 0 else 0.3, r * 1.08, label, fontsize=8, color="#64748B")
    ax.grid(alpha=0.2, which="both")
    ax.legend(frameon=False, fontsize=8, loc="lower right")
    _stamp(fig, is_sample)
    fig.tight_layout()
    fig.savefig(out / "radius_vs_period.png", dpi=130)
    plt.close(fig)
    return "radius_vs_period.png"


def plot_radius_coverage(cov: pd.DataFrame, out: Path, is_sample: bool) -> str:
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 3.8))
    colors = [METHOD_COLORS.get(m, METHOD_COLORS["Other"]) for m in cov.index]
    ax.barh(cov.index[::-1], cov["radius_pct"][::-1], color=colors[::-1])
    for i, (_m, r) in enumerate(cov[::-1].iterrows()):
        ax.text(r["radius_pct"] + 1, i, f"{r['radius_pct']:.0f}% of {int(r['planets'])}", va="center", fontsize=8)
    ax.set(xlim=(0, 115), xlabel="% of planets with a measured radius", title="Who gets dropped when you filter for radius?")
    ax.grid(alpha=0.25, axis="x")
    _stamp(fig, is_sample)
    fig.tight_layout()
    fig.savefig(out / "radius_coverage.png", dpi=130)
    plt.close(fig)
    return "radius_coverage.png"


def run(mode: str = "sample", out_dir: str | Path = "outputs/sample", params: dict | None = None) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    is_sample = mode == "sample"

    print(f"[1/5] Loading {mode} catalog", flush=True)
    catalog = load_data.load(mode)
    print(f"      {len(catalog):,} planets", flush=True)

    print("[2/5] Missingness report on the FULL catalog (before filtering)", flush=True)
    miss = missingness(catalog)
    cov = radius_coverage_by_method(catalog)
    plotted = scatter_frame(catalog)
    print(f"      radius missing for {int(miss.loc['pl_rade', 'missing'])} planets; {len(plotted)} plottable", flush=True)

    print("[3/5] Charts", flush=True)
    charts = [
        {"file": plot_discoveries(catalog, out, is_sample), "title": "Discoveries by method over time",
         "caption": "Each method dominates a different era - Kepler/TESS made transits the majority."},
        {"file": plot_radius_period(catalog, out, is_sample), "title": "Radius vs. orbital period",
         "caption": "Transits favour short periods; imaging finds giants far from their stars."},
        {"file": plot_radius_coverage(cov, out, is_sample), "title": "Radius coverage by method",
         "caption": "Filtering to planets with a radius removes most radial-velocity and microlensing discoveries."},
    ]

    print("[4/5] Baseline: can period + radius alone reveal the discovery method?", flush=True)
    b = method_baseline(catalog)

    print("[5/5] Writing results", flush=True)
    top_method = catalog["discoverymethod"].value_counts().idxmax()
    results = {
        "pack": PACK,
        "mode": mode,
        "is_sample": is_sample,
        "generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "headline": f"{len(catalog):,} planets; {len(plotted):,} plottable. Period + radius predict the method with macro F1 "
                    f"{b['tree_macro_f1']:.2f} (majority baseline {b['majority_macro_f1']:.2f}) - that gap is detection bias.",
        "metrics": [
            {"key": "planets", "label": "Planets in catalog", "value": int(len(catalog)), "unit": "", "better": None, "hint": "Rows in pscomppars."},
            {"key": "plottable", "label": "With radius and period", "value": int(len(plotted)), "unit": "", "better": None,
             "hint": f"{len(catalog) - len(plotted):,} dropped from the scatter plot."},
            {"key": "radius_missing_pct", "label": "Radius missing", "value": float(miss.loc["pl_rade", "missing_pct"]), "unit": "%", "better": None,
             "hint": "Reported before filtering."},
            {"key": "majority_macro_f1", "label": "Majority baseline F1", "value": round(b["majority_macro_f1"], 3), "unit": "macro", "better": "higher",
             "hint": f"Always predicts the most common method ({top_method})."},
            {"key": "tree_macro_f1", "label": "Decision tree F1", "value": round(b["tree_macro_f1"], 3), "unit": "macro", "better": "higher",
             "hint": "Depth-4 tree on log period and log radius."},
        ],
        "tables": [
            {"title": "Missingness (full catalog, before filtering)", "columns": ["column", "missing", "total", "missing_pct"],
             "rows": [[c, int(r.missing), int(r.total), float(r.missing_pct)] for c, r in miss.iterrows()]},
            {"title": "Radius coverage by method", "columns": ["method", "planets", "with_radius", "with_period", "radius_pct"],
             "rows": [[m, int(r.planets), int(r.with_radius), int(r.with_period), float(r.radius_pct)] for m, r in cov.iterrows()]},
        ],
        "charts": charts,
        "checks": [
            {"name": "Missingness reported before filtering", "passed": int(miss.loc["pl_rade", "total"]) == len(catalog),
             "detail": f"Report covers all {len(catalog):,} planets; the scatter uses {len(plotted):,}."},
            {"name": "One row per planet", "passed": bool(catalog["pl_name"].is_unique), "detail": "pscomppars is one composite row per planet."},
            {"name": "Positive values for log axes", "passed": bool((plotted[["pl_rade", "pl_orbper"]] > 0).all().all()),
             "detail": "Log scales need strictly positive radius and period."},
        ],
        "notes": [
            "This is the catalog of planets we have found, shaped by how each method detects them - not a census of all planets.",
            "Transits favour large planets on short orbits; radial velocity favours massive planets; imaging favours young giants far out.",
            f"Cite: NASA Exoplanet Archive, Planetary Systems Composite Parameters, doi:{load_data.DOI}, with your retrieval date.",
        ],
        "provenance": load_data.provenance(mode),
    }
    (out / "results.json").write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print(f"Done: {results['headline']}", flush=True)
    return results


if __name__ == "__main__":
    import matplotlib

    matplotlib.use("Agg")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", default="sample", choices=["sample", "real"])
    parser.add_argument("--out", default=None)
    parser.add_argument("--param", action="append", default=[])
    args = parser.parse_args()
    run(args.mode, args.out or f"outputs/{args.mode}", dict(p.split("=", 1) for p in args.param))
