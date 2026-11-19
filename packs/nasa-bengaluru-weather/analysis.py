"""Explore NASA POWER daily weather for an Indian city and set a forecasting baseline.

    python analysis.py --mode sample
    python analysis.py --mode real --param city=bengaluru --param compare_city=chennai \
        --param start=2015-01-01 --param end=2024-12-31
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

import numpy as np
import pandas as pd

import load_data

PACK = "nasa-bengaluru-weather"
COLORS = {"primary": "#0EA5E9", "compare": "#F97316", "band": "#BAE6FD", "rain": "#6366F1", "muted": "#94A3B8"}


def missing_summary(frame: pd.DataFrame) -> pd.DataFrame:
    summary = pd.DataFrame({
        "missing_days": frame.isna().sum(),
        "total_days": len(frame),
    })
    summary["missing_pct"] = (summary["missing_days"] / summary["total_days"] * 100).round(2)
    summary["units"] = [load_data.PARAMETERS[c][1] for c in summary.index]
    return summary


def monthly(frame: pd.DataFrame) -> pd.DataFrame:
    """Monthly aggregates. A month's rainfall total is NaN if any day in it is missing."""
    grouped = frame.resample("MS")
    out = pd.DataFrame({
        "t2m_mean": grouped["T2M"].mean(),
        "t2m_max_mean": grouped["T2M_MAX"].mean(),
        "t2m_min_mean": grouped["T2M_MIN"].mean(),
        "precip_total": grouped["PRECTOTCORR"].sum(min_count=1),
        "precip_missing_days": grouped["PRECTOTCORR"].apply(lambda s: int(s.isna().sum())),
    })
    out.loc[out["precip_missing_days"] > 0, "precip_total"] = np.nan
    return out


def climatology(frame: pd.DataFrame) -> pd.DataFrame:
    m = monthly(frame)
    return m.groupby(m.index.month).agg(t2m_mean=("t2m_mean", "mean"), precip_total=("precip_total", "mean"))


def next_day_baselines(frame: pd.DataFrame, holdout_days: int = 365) -> dict:
    """Forecast tomorrow's mean temperature with two baselines on the final ``holdout_days``."""
    t = frame["T2M"]
    split = t.index[-holdout_days] if len(t) > holdout_days * 1.5 else t.index[len(t) // 2]
    train, test = t[t.index < split], t[t.index >= split]
    # Persistence: tomorrow = today.
    persistence = t.shift(1).loc[test.index]
    # Climatology: mean for that day-of-year in training years, smoothed with a circular 15-day window.
    doy_mean = train.groupby(train.index.dayofyear).mean().reindex(range(1, 367))
    padded = pd.concat([doy_mean.iloc[-15:], doy_mean, doy_mean.iloc[:15]])
    smooth = padded.rolling(15, center=True, min_periods=1).mean().iloc[15:-15]
    smooth.index = range(1, 367)
    clim = pd.Series(test.index.dayofyear, index=test.index).map(smooth)
    valid = test.notna() & persistence.notna() & clim.notna()
    return {
        "split": split,
        "test": test[valid],
        "persistence": persistence[valid],
        "climatology": clim[valid],
        "persistence_mae": float((test[valid] - persistence[valid]).abs().mean()),
        "climatology_mae": float((test[valid] - clim[valid]).abs().mean()),
        "n_eval": int(valid.sum()),
        "n_skipped": int((~valid).sum()),
    }


def _stamp(fig, is_sample):
    if is_sample:
        fig.text(0.99, 0.01, "SYNTHETIC SAMPLE - not real weather", ha="right", va="bottom", fontsize=8, color="#F97316")


def plot_monthly_temperature(m: pd.DataFrame, city: str, out: Path, is_sample: bool) -> str:
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.fill_between(m.index, m["t2m_min_mean"], m["t2m_max_mean"], color=COLORS["band"], alpha=0.7, label="Mean daily min-max")
    ax.plot(m.index, m["t2m_mean"], color=COLORS["primary"], lw=2, label="Mean temperature")
    ax.set(ylabel="°C", title=f"{city.title()} - monthly temperature (NASA POWER T2M, gridded)")
    ax.grid(alpha=0.25)
    ax.legend(frameon=False, loc="upper left")
    _stamp(fig, is_sample)
    fig.tight_layout()
    fig.savefig(out / "monthly_temperature.png", dpi=130)
    plt.close(fig)
    return "monthly_temperature.png"


def plot_monthly_precip(m: pd.DataFrame, city: str, out: Path, is_sample: bool) -> str:
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.bar(m.index, m["precip_total"].fillna(0), width=25, color=COLORS["rain"], label="Monthly total")
    gaps = m[m["precip_total"].isna()]
    if len(gaps):
        ax.scatter(gaps.index, np.zeros(len(gaps)), marker="x", color="#EF4444", zorder=3, label="Incomplete month (excluded)")
    ax.set(ylabel="mm / month", title=f"{city.title()} - monthly precipitation (PRECTOTCORR)")
    ax.grid(alpha=0.25, axis="y")
    ax.legend(frameon=False, loc="upper left")
    _stamp(fig, is_sample)
    fig.tight_layout()
    fig.savefig(out / "monthly_precipitation.png", dpi=130)
    plt.close(fig)
    return "monthly_precipitation.png"


def plot_comparison(clims: dict[str, pd.DataFrame], out: Path, is_sample: bool) -> str:
    import matplotlib.pyplot as plt

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4))
    months = ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"]
    width = 0.8 / len(clims)
    for i, (city, c) in enumerate(clims.items()):
        color = COLORS["primary"] if i == 0 else COLORS["compare"]
        ax1.plot(c.index, c["t2m_mean"], marker="o", color=color, lw=2, label=city.title())
        ax2.bar(c.index + (i - (len(clims) - 1) / 2) * width, c["precip_total"], width=width, color=color, label=city.title())
    for ax in (ax1, ax2):
        ax.set_xticks(range(1, 13), months)
        ax.grid(alpha=0.25)
        ax.legend(frameon=False)
    ax1.set(title="Average monthly temperature", ylabel="°C")
    ax2.set(title="Average monthly precipitation", ylabel="mm / month")
    _stamp(fig, is_sample)
    fig.tight_layout()
    fig.savefig(out / "city_comparison.png", dpi=130)
    plt.close(fig)
    return "city_comparison.png"


def plot_baselines(b: dict, out: Path, is_sample: bool) -> str:
    import matplotlib.pyplot as plt

    window = b["test"].index[:120]
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(window, b["test"].loc[window], color="#0F172A", lw=1.5, label="Actual T2M")
    ax.plot(window, b["persistence"].loc[window], color=COLORS["compare"], lw=1.2, label="Persistence (yesterday)")
    ax.plot(window, b["climatology"].loc[window], color=COLORS["muted"], lw=1.6, ls="--", label="Climatology")
    ax.set(ylabel="°C", title="Next-day temperature baselines (first 120 holdout days)")
    ax.grid(alpha=0.25)
    ax.legend(frameon=False, ncol=3)
    fig.autofmt_xdate()
    _stamp(fig, is_sample)
    fig.tight_layout()
    fig.savefig(out / "next_day_baselines.png", dpi=130)
    plt.close(fig)
    return "next_day_baselines.png"


def run(mode: str = "sample", out_dir: str | Path = "outputs/sample", params: dict | None = None) -> dict:
    params = params or {}
    city = params.get("city", "bengaluru")
    compare_city = params.get("compare_city", "chennai" if mode == "sample" else "none")
    start, end = params.get("start") or None, params.get("end") or None
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    is_sample = mode == "sample"

    print(f"[1/5] Loading {mode} data for {city}", flush=True)
    frame = load_data.load(mode, city, start, end)
    print(f"      {len(frame):,} days {frame.index.min():%Y-%m-%d} -> {frame.index.max():%Y-%m-%d}", flush=True)

    print("[2/5] Summarising missing values (fill marker -999 -> NaN)", flush=True)
    miss = missing_summary(frame)

    print("[3/5] Monthly aggregation", flush=True)
    m = monthly(frame)
    charts = [
        {"file": plot_monthly_temperature(m, city, out, is_sample), "title": "Monthly temperature",
         "caption": "Mean of daily T2M with the average daily min-max band."},
        {"file": plot_monthly_precip(m, city, out, is_sample), "title": "Monthly precipitation",
         "caption": "Months with any missing day are excluded instead of under-counted."},
    ]

    clims = {city: climatology(frame)}
    if compare_city and compare_city not in ("none", city):
        print(f"[3b]  Loading comparison city {compare_city}", flush=True)
        other = load_data.load(mode, compare_city, start, end)
        clims[compare_city] = climatology(other)
    charts.append({"file": plot_comparison(clims, out, is_sample), "title": "Seasonal cycle" + (" comparison" if len(clims) > 1 else ""),
                   "caption": "Same method and date range for each location." if len(clims) > 1 else "Average month-by-month cycle."})

    print("[4/5] Next-day temperature baselines on the final year", flush=True)
    b = next_day_baselines(frame)
    charts.append({"file": plot_baselines(b, out, is_sample), "title": "Next-day baselines",
                   "caption": "Beat both lines with a model to complete the main challenge."})

    print("[5/5] Writing results", flush=True)
    best = min(b["persistence_mae"], b["climatology_mae"])
    lat, lon = load_data.CITIES[city]
    total_missing = int(miss["missing_days"].sum())
    results = {
        "pack": PACK,
        "mode": mode,
        "is_sample": is_sample,
        "generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "headline": f"{city.title()}: mean {frame['T2M'].mean():.1f} °C, {np.nanmean(m['precip_total'].groupby(m.index.year).sum(min_count=1)):.0f} mm/yr; "
                    f"best next-day baseline MAE {best:.2f} °C",
        "metrics": [
            {"key": "mean_t2m", "label": "Mean temperature", "value": round(float(frame["T2M"].mean()), 2), "unit": "°C", "better": None,
             "hint": "Average of daily T2M over the whole range."},
            {"key": "persistence_mae", "label": "Persistence MAE", "value": round(b["persistence_mae"], 3), "unit": "°C", "better": "lower",
             "hint": "Tomorrow = today."},
            {"key": "climatology_mae", "label": "Climatology MAE", "value": round(b["climatology_mae"], 3), "unit": "°C", "better": "lower",
             "hint": "Smoothed day-of-year mean from the training years."},
            {"key": "missing_values", "label": "Missing values", "value": total_missing, "unit": "cells", "better": None,
             "hint": "Fill markers (-999) converted to NaN across all parameters."},
            {"key": "days", "label": "Days analysed", "value": int(len(frame)), "unit": "days", "better": None, "hint": ""},
        ],
        "tables": [
            {"title": "Missing-data summary", "columns": ["parameter", "missing_days", "total_days", "missing_pct", "units"],
             "rows": [[p, int(r.missing_days), int(r.total_days), float(r.missing_pct), r.units] for p, r in miss.iterrows()]},
            {"title": "Seasonal cycle", "columns": ["month"] + [f"{c}_{k}" for c in clims for k in ("t2m_mean", "precip_total")],
             "rows": [[int(mo)] + [round(float(clims[c].loc[mo, k]), 2) if pd.notna(clims[c].loc[mo, k]) else None
                                   for c in clims for k in ("t2m_mean", "precip_total")] for mo in clims[city].index]},
            {"title": "Location metadata", "columns": ["field", "value"], "rows": [
                ["requested latitude", lat], ["requested longitude", lon], ["time standard", load_data.TIME_STANDARD],
                ["fill value", -999], ["temperature units", "°C"], ["precipitation units", "mm/day"],
                ["grid", "POWER estimates for the grid cell containing the point - not a station"]]},
        ],
        "charts": charts,
        "checks": [
            {"name": "Fill markers stay missing", "passed": bool((frame.min(numeric_only=True) > -100).all()),
             "detail": f"{total_missing} cells marked -999 became NaN; none were treated as real values."},
            {"name": "Daily index is complete", "passed": len(frame) == len(pd.date_range(frame.index.min(), frame.index.max())),
             "detail": "Every calendar day in range has a row."},
            {"name": "Incomplete months excluded from rainfall", "passed": bool(m.loc[m["precip_missing_days"] > 0, "precip_total"].isna().all()),
             "detail": f"{int((m['precip_missing_days'] > 0).sum())} month(s) flagged."},
        ],
        "notes": [
            "POWER values are gridded estimates for the requested coordinates, not station observations.",
            f"Next-day baselines evaluated on {b['n_eval']} days from {b['split']:%Y-%m-%d}; {b['n_skipped']} skipped for missing values.",
            "Synthetic sample: the charts only prove the pipeline works." if is_sample else "Real NASA POWER data - cite the POWER project when you publish.",
        ],
        "provenance": load_data.provenance(mode, city, start, end),
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
    parser.add_argument("--param", action="append", default=[], help="key=value (city, compare_city, start, end)")
    args = parser.parse_args()
    params = dict(p.split("=", 1) for p in args.param)
    run(args.mode, args.out or f"outputs/{args.mode}", params)
