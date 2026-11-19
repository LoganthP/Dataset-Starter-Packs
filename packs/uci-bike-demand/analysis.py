"""Next-hour bike demand: historical baseline vs. gradient-boosted regression.

Usage:
    python analysis.py --mode sample --out outputs/sample
    python analysis.py --mode real   --out outputs/real --param holdout_fraction=0.2

Writes ``results.json`` plus PNG charts into ``--out``.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

import numpy as np
import pandas as pd

import load_data

PACK = "uci-bike-demand"
COLORS = {"baseline": "#94A3B8", "model": "#6366F1", "actual": "#0F172A", "accent": "#F97316", "teal": "#14B8A6"}

# Prediction task: at the end of hour t-1, estimate total rentals (cnt) in hour t.
# Known in advance: the calendar for hour t (hour, weekday, month, holiday flags).
# Known at prediction time: demand and *observed* weather up to hour t-1.
# We deliberately do NOT use weather for hour t itself - that would require a forecast,
# and the dataset contains observations, not forecasts.
CALENDAR_FEATURES = ["hr", "dow", "mnth", "yr", "holiday", "workingday", "season"]
LAG_FEATURES = ["cnt_lag1", "cnt_lag2", "cnt_lag24", "cnt_lag168"]
WEATHER_LAG_FEATURES = ["temp_lag1", "atemp_lag1", "hum_lag1", "windspeed_lag1", "weathersit_lag1"]
FEATURES = CALENDAR_FEATURES + LAG_FEATURES + WEATHER_LAG_FEATURES


def to_hourly_grid(df: pd.DataFrame) -> pd.DataFrame:
    """Reindex onto a complete hourly grid so that lags are time-based, not row-based.

    The real hour.csv skips some hours. Shifting rows would silently compare the wrong hours.
    """
    grid = pd.date_range(df["timestamp"].min(), df["timestamp"].max(), freq="h")
    full = df.set_index("timestamp").reindex(grid)
    full.index.name = "timestamp"
    full["observed"] = full["cnt"].notna()
    # Calendar values are known for every hour, even ones missing from the file.
    full["hr"] = full.index.hour
    full["dow"] = full.index.dayofweek
    full["mnth"] = full.index.month
    full["yr"] = full.index.year - 2011
    full["season"] = full["season"].ffill().bfill()
    day = full.index.normalize()
    for col in ("holiday", "workingday"):
        full[col] = full.groupby(day)[col].transform(lambda s: s.ffill().bfill())
    # A whole day missing from the file: assume no holiday, working day on Mon-Fri.
    full["holiday"] = full["holiday"].fillna(0)
    full["workingday"] = full["workingday"].fillna(((full["dow"] < 5) & (full["holiday"] == 0)).astype(float))
    return full.reset_index()


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    full = to_hourly_grid(df)
    for lag in (1, 2, 24, 168):
        full[f"cnt_lag{lag}"] = full["cnt"].shift(lag)
    for col in ("temp", "atemp", "hum", "windspeed", "weathersit"):
        full[f"{col}_lag1"] = full[col].shift(1)
    return full[full["observed"]].reset_index(drop=True)


def feature_matrix(frame: pd.DataFrame) -> pd.DataFrame:
    X = frame[FEATURES].astype(float)
    leaked = [c for c in load_data.LEAKY_COLUMNS if c in X.columns]
    if leaked:
        raise AssertionError(f"Leakage: {leaked} are components of the target and must not be features.")
    return X


def chronological_split(frame: pd.DataFrame, holdout_fraction: float = 0.2):
    if not 0.05 <= holdout_fraction <= 0.5:
        raise ValueError("holdout_fraction must be between 0.05 and 0.5")
    cutoff = frame["timestamp"].quantile(1 - holdout_fraction).floor("D")
    train = frame[frame["timestamp"] < cutoff].copy()
    test = frame[frame["timestamp"] >= cutoff].copy()
    return train, test, cutoff


def historical_baseline(train: pd.DataFrame, test: pd.DataFrame) -> np.ndarray:
    """Average demand for the same weekday and hour in the training period."""
    table = train.groupby(["dow", "hr"])["cnt"].mean()
    by_hour = train.groupby("hr")["cnt"].mean()
    keys = list(zip(test["dow"], test["hr"]))
    pred = np.array([table.get(k, np.nan) for k in keys], dtype=float)
    fallback = test["hr"].map(by_hour).fillna(train["cnt"].mean()).to_numpy()
    return np.where(np.isnan(pred), fallback, pred)


def fit_model(train: pd.DataFrame):
    from sklearn.ensemble import HistGradientBoostingRegressor

    model = HistGradientBoostingRegressor(max_iter=300, learning_rate=0.08, random_state=0)
    model.fit(feature_matrix(train), train["cnt"])
    return model


def mae(y_true, y_pred) -> float:
    return float(np.mean(np.abs(np.asarray(y_true, float) - np.asarray(y_pred, float))))


def _stamp(fig, is_sample: bool):
    if is_sample:
        fig.text(0.99, 0.01, "SYNTHETIC SAMPLE - not real results", ha="right", va="bottom",
                 fontsize=8, color=COLORS["accent"], alpha=0.9)


def plot_hourly_profile(df, out: Path, is_sample: bool) -> str:
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 4))
    for flag, label, color in ((1, "Working day", COLORS["model"]), (0, "Weekend / holiday", COLORS["accent"])):
        prof = df[df["workingday"] == flag].groupby("hr")["cnt"].mean()
        ax.plot(prof.index, prof.values, marker="o", ms=3, lw=2, color=color, label=label)
    ax.set(xlabel="Hour of day", ylabel="Average rentals per hour", title="Hourly demand profile")
    ax.set_xticks(range(0, 24, 2))
    ax.grid(alpha=0.25)
    ax.legend(frameon=False)
    _stamp(fig, is_sample)
    fig.tight_layout()
    fig.savefig(out / "hourly_profile.png", dpi=130)
    plt.close(fig)
    return "hourly_profile.png"


def plot_holdout(test, base, pred, out: Path, is_sample: bool) -> str:
    import matplotlib.pyplot as plt

    window = test.head(24 * 14)
    n = len(window)
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(window["timestamp"], window["cnt"], color=COLORS["actual"], lw=1.4, label="Actual")
    ax.plot(window["timestamp"], base[:n], color=COLORS["baseline"], lw=1.2, ls="--", label="Historical baseline")
    ax.plot(window["timestamp"], pred[:n], color=COLORS["model"], lw=1.4, label="Model")
    ax.set(ylabel="Rentals per hour", title="First two weeks of the chronological holdout")
    ax.grid(alpha=0.25)
    ax.legend(frameon=False, ncol=3)
    fig.autofmt_xdate()
    _stamp(fig, is_sample)
    fig.tight_layout()
    fig.savefig(out / "holdout_window.png", dpi=130)
    plt.close(fig)
    return "holdout_window.png"


def plot_error_by_hour(by_hour: pd.DataFrame, out: Path, is_sample: bool) -> str:
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 4))
    x = by_hour.index.to_numpy()
    ax.bar(x - 0.2, by_hour["baseline_mae"], width=0.4, color=COLORS["baseline"], label="Historical baseline")
    ax.bar(x + 0.2, by_hour["model_mae"], width=0.4, color=COLORS["model"], label="Model")
    ax.set(xlabel="Hour of day", ylabel="MAE (rentals)", title="Holdout error by hour of day")
    ax.set_xticks(range(0, 24, 2))
    ax.grid(alpha=0.25, axis="y")
    ax.legend(frameon=False)
    _stamp(fig, is_sample)
    fig.tight_layout()
    fig.savefig(out / "error_by_hour.png", dpi=130)
    plt.close(fig)
    return "error_by_hour.png"


def run(mode: str = "sample", out_dir: str | Path = "outputs/sample", params: dict | None = None) -> dict:
    params = params or {}
    holdout_fraction = float(params.get("holdout_fraction", 0.2))
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    is_sample = mode == "sample"

    print(f"[1/5] Loading {mode} data", flush=True)
    raw = load_data.load(mode)
    print(f"      {len(raw):,} rows from {raw['timestamp'].min():%Y-%m-%d} to {raw['timestamp'].max():%Y-%m-%d}", flush=True)

    print("[2/5] Building time-based lag features on a complete hourly grid", flush=True)
    frame = build_features(raw)
    expected_hours = int((raw["timestamp"].max() - raw["timestamp"].min()) / pd.Timedelta(hours=1)) + 1
    missing_hours = expected_hours - len(raw)

    print(f"[3/5] Chronological split (holdout fraction {holdout_fraction})", flush=True)
    train, test, cutoff = chronological_split(frame, holdout_fraction)

    print("[4/5] Fitting baseline and model", flush=True)
    base = historical_baseline(train, test)
    model = fit_model(train)
    pred = np.clip(model.predict(feature_matrix(test)), 0, None)

    print("[5/5] Evaluating and charting", flush=True)
    base_mae, model_mae = mae(test["cnt"], base), mae(test["cnt"], pred)
    errs = test.assign(baseline_err=np.abs(test["cnt"] - base), model_err=np.abs(test["cnt"] - pred))
    by_hour = errs.groupby("hr").agg(baseline_mae=("baseline_err", "mean"), model_mae=("model_err", "mean"))
    charts = [
        {"file": plot_hourly_profile(raw, out, is_sample), "title": "Hourly demand profile",
         "caption": "Commuter peaks on working days, a single afternoon hump on weekends."},
        {"file": plot_holdout(test, base, pred, out, is_sample), "title": "Holdout: actual vs. predicted",
         "caption": "The model tracks day-to-day swings that a fixed weekday-hour average cannot."},
        {"file": plot_error_by_hour(by_hour, out, is_sample), "title": "Error by hour of day",
         "caption": "Where the remaining error lives - a good place to start improving."},
    ]
    X_cols = list(feature_matrix(test.head(1)).columns)
    improvement = (base_mae - model_mae) / base_mae * 100 if base_mae else 0.0

    results = {
        "pack": PACK,
        "mode": mode,
        "is_sample": is_sample,
        "generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "headline": f"Model MAE {model_mae:.1f} vs. baseline {base_mae:.1f} rentals/hour ({improvement:+.0f}% better)"
        if improvement >= 0 else f"Model MAE {model_mae:.1f} is worse than baseline {base_mae:.1f} - investigate!",
        "metrics": [
            {"key": "baseline_mae", "label": "Baseline MAE", "value": round(base_mae, 2), "unit": "rentals/h", "better": "lower",
             "hint": "Mean demand for the same weekday and hour in the training period."},
            {"key": "model_mae", "label": "Model MAE", "value": round(model_mae, 2), "unit": "rentals/h", "better": "lower",
             "hint": "HistGradientBoostingRegressor on calendar, lagged demand and lagged observed weather."},
            {"key": "improvement_pct", "label": "Improvement", "value": round(improvement, 1), "unit": "%", "better": "higher",
             "hint": "Relative MAE reduction over the baseline."},
            {"key": "holdout_hours", "label": "Holdout hours", "value": int(len(test)), "unit": "h", "better": None,
             "hint": f"Holdout starts {cutoff:%Y-%m-%d}; training ends before it."},
            {"key": "missing_hours", "label": "Hours missing in file", "value": int(missing_hours), "unit": "h", "better": None,
             "hint": "Lags are computed on a complete hourly grid so gaps don't shift the wrong hours."},
        ],
        "tables": [
            {"title": "MAE by hour of day", "columns": ["hour", "baseline_mae", "model_mae"],
             "rows": [[int(h), round(float(r.baseline_mae), 2), round(float(r.model_mae), 2)] for h, r in by_hour.iterrows()]},
            {"title": "Feature set", "columns": ["feature", "group"],
             "rows": [[c, "calendar" if c in CALENDAR_FEATURES else "lagged demand" if c in LAG_FEATURES else "lagged weather"]
                      for c in X_cols]},
        ],
        "charts": charts,
        "checks": [
            {"name": "No target leakage", "passed": not any(c in X_cols for c in load_data.LEAKY_COLUMNS),
             "detail": "casual and registered sum to cnt, so they are excluded from the feature matrix."},
            {"name": "Holdout is strictly after training", "passed": bool(train["timestamp"].max() < test["timestamp"].min()),
             "detail": f"Train ends {train['timestamp'].max():%Y-%m-%d %H:00}, holdout starts {test['timestamp'].min():%Y-%m-%d %H:00}."},
            {"name": "Weather is lagged (no forecast needed)", "passed": not any(c in X_cols for c in ("temp", "atemp", "hum", "windspeed", "weathersit")),
             "detail": "Only weather observed in hour t-1 is used to predict hour t."},
        ],
        "notes": [
            "Task: predict total rentals for the next hour using information available at the end of the current hour.",
            "Scores from the synthetic sample only prove the pipeline runs; switch to real mode for a meaningful result." if is_sample
            else "Real UCI data (Capital Bikeshare, Washington D.C., 2011-2012).",
        ],
        "split": {"cutoff": f"{cutoff:%Y-%m-%d}", "train_rows": int(len(train)), "test_rows": int(len(test))},
        "provenance": load_data.provenance(mode),
    }
    (out / "results.json").write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print(f"Done: {results['headline']}", flush=True)
    return results


def _parse_params(items: list[str]) -> dict:
    params = {}
    for item in items:
        key, _, value = item.partition("=")
        params[key.strip()] = value.strip()
    return params


if __name__ == "__main__":
    import matplotlib

    matplotlib.use("Agg")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", default="sample", choices=["sample", "real"])
    parser.add_argument("--out", default=None)
    parser.add_argument("--param", action="append", default=[], help="key=value, e.g. holdout_fraction=0.2")
    args = parser.parse_args()
    run(args.mode, args.out or f"outputs/{args.mode}", _parse_params(args.param))
