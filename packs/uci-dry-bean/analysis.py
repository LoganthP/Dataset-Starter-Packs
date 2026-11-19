"""Classify dry beans from shape features: majority baseline vs. a real classifier.

    python analysis.py --mode sample
    python analysis.py --mode real --param model=random_forest --param test_size=0.25
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

import numpy as np
import pandas as pd

import load_data

PACK = "uci-dry-bean"
COLORS = {"baseline": "#94A3B8", "model": "#22C55E", "accent": "#F97316"}


def split(df: pd.DataFrame, test_size: float = 0.25, seed: int = 42):
    """Stratified split so every class - including rare ones - appears in the evaluation set."""
    from sklearn.model_selection import train_test_split

    if not 0.1 <= test_size <= 0.5:
        raise ValueError("test_size must be between 0.1 and 0.5")
    X, y = df[load_data.FEATURES], df[load_data.TARGET]
    return train_test_split(X, y, test_size=test_size, stratify=y, random_state=seed)


def make_model(name: str = "logreg"):
    """Preprocessing lives inside the pipeline, so the scaler is fit on training data only."""
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    if name == "logreg":
        return Pipeline([("scale", StandardScaler()), ("clf", LogisticRegression(max_iter=3000))])
    if name == "random_forest":
        return Pipeline([("scale", StandardScaler()), ("clf", RandomForestClassifier(n_estimators=300, random_state=0, n_jobs=-1))])
    raise ValueError("model must be 'logreg' or 'random_forest'")


def evaluate(y_true, y_pred, classes) -> pd.DataFrame:
    from sklearn.metrics import precision_recall_fscore_support

    p, r, f, s = precision_recall_fscore_support(y_true, y_pred, labels=classes, zero_division=0)
    return pd.DataFrame({"precision": p, "recall": r, "f1": f, "support": s}, index=classes)


def _stamp(fig, is_sample):
    if is_sample:
        fig.text(0.99, 0.01, "SYNTHETIC SAMPLE - not real results", ha="right", va="bottom", fontsize=8, color=COLORS["accent"])


def plot_confusion(y_true, y_pred, classes, out: Path, is_sample: bool) -> str:
    import matplotlib.pyplot as plt
    from sklearn.metrics import confusion_matrix

    cm = confusion_matrix(y_true, y_pred, labels=classes, normalize="true")
    fig, ax = plt.subplots(figsize=(7, 6))
    im = ax.imshow(cm, cmap="Greens", vmin=0, vmax=1)
    ax.set_xticks(range(len(classes)), classes, rotation=45, ha="right")
    ax.set_yticks(range(len(classes)), classes)
    for i in range(len(classes)):
        for j in range(len(classes)):
            ax.text(j, i, f"{cm[i, j]:.2f}", ha="center", va="center", fontsize=8, color="white" if cm[i, j] > 0.6 else "#0F172A")
    ax.set(xlabel="Predicted", ylabel="True", title="Confusion matrix (row-normalised recall)")
    fig.colorbar(im, ax=ax, fraction=0.046)
    _stamp(fig, is_sample)
    fig.tight_layout()
    fig.savefig(out / "confusion_matrix.png", dpi=130)
    plt.close(fig)
    return "confusion_matrix.png"


def plot_per_class(base: pd.DataFrame, model: pd.DataFrame, out: Path, is_sample: bool) -> str:
    import matplotlib.pyplot as plt

    x = np.arange(len(model))
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.bar(x - 0.2, base["f1"], width=0.4, color=COLORS["baseline"], label="Majority baseline")
    ax.bar(x + 0.2, model["f1"], width=0.4, color=COLORS["model"], label="Classifier")
    for i, s in enumerate(model["support"]):
        ax.text(i, 1.02, f"n={int(s)}", ha="center", fontsize=8, color="#64748B")
    ax.set_xticks(x, model.index, rotation=30, ha="right")
    ax.set(ylim=(0, 1.1), ylabel="F1 score", title="Per-class F1 on the held-out set")
    ax.grid(alpha=0.25, axis="y")
    ax.legend(frameon=False, loc="lower right")
    _stamp(fig, is_sample)
    fig.tight_layout()
    fig.savefig(out / "per_class_f1.png", dpi=130)
    plt.close(fig)
    return "per_class_f1.png"


def plot_class_balance(df: pd.DataFrame, out: Path, is_sample: bool) -> str:
    import matplotlib.pyplot as plt

    counts = df[load_data.TARGET].value_counts()
    fig, ax = plt.subplots(figsize=(8, 3.5))
    ax.bar(counts.index, counts.values, color=[COLORS["accent"] if v == counts.min() else COLORS["model"] for v in counts.values])
    ax.set(ylabel="Beans", title="Class balance - the rarest class is highlighted")
    ax.grid(alpha=0.25, axis="y")
    plt.setp(ax.get_xticklabels(), rotation=30, ha="right")
    _stamp(fig, is_sample)
    fig.tight_layout()
    fig.savefig(out / "class_balance.png", dpi=130)
    plt.close(fig)
    return "class_balance.png"


def run(mode: str = "sample", out_dir: str | Path = "outputs/sample", params: dict | None = None) -> dict:
    from sklearn.dummy import DummyClassifier
    from sklearn.metrics import accuracy_score, f1_score

    params = params or {}
    model_name = params.get("model", "logreg")
    test_size = float(params.get("test_size", 0.25))
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    is_sample = mode == "sample"

    print(f"[1/5] Loading {mode} data", flush=True)
    df = load_data.load(mode)
    classes = sorted(df[load_data.TARGET].unique())
    print(f"      {len(df):,} beans, {len(classes)} classes", flush=True)

    print(f"[2/5] Stratified split (test_size={test_size})", flush=True)
    X_tr, X_te, y_tr, y_te = split(df, test_size)

    print(f"[3/5] Fitting majority baseline and {model_name}", flush=True)
    dummy = DummyClassifier(strategy="most_frequent").fit(X_tr, y_tr)
    model = make_model(model_name).fit(X_tr, y_tr)
    yb, ym = dummy.predict(X_te), model.predict(X_te)

    print("[4/5] Evaluating", flush=True)
    base_tbl, model_tbl = evaluate(y_te, yb, classes), evaluate(y_te, ym, classes)
    scaler_mean = model.named_steps["scale"].mean_
    scaler_fit_on_train = bool(np.allclose(scaler_mean, X_tr.mean().to_numpy()))
    worst = model_tbl["f1"].idxmin()
    m = {
        "base_acc": accuracy_score(y_te, yb), "base_f1": f1_score(y_te, yb, average="macro", zero_division=0),
        "model_acc": accuracy_score(y_te, ym), "model_f1": f1_score(y_te, ym, average="macro", zero_division=0),
    }

    print("[5/5] Charts and results", flush=True)
    charts = [
        {"file": plot_class_balance(df, out, is_sample), "title": "Class balance", "caption": "Imbalance is why accuracy alone can mislead."},
        {"file": plot_confusion(y_te, ym, classes, out, is_sample), "title": "Confusion matrix", "caption": "Read rows: where does each true class end up?"},
        {"file": plot_per_class(base_tbl, model_tbl, out, is_sample), "title": "Per-class F1",
         "caption": "The baseline scores zero on every class except the majority one."},
    ]
    results = {
        "pack": PACK,
        "mode": mode,
        "is_sample": is_sample,
        "generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "headline": f"{model_name}: macro F1 {m['model_f1']:.3f} vs. majority baseline {m['base_f1']:.3f} "
                    f"(accuracy {m['model_acc']:.3f} vs. {m['base_acc']:.3f}). Weakest class: {worst}.",
        "metrics": [
            {"key": "baseline_accuracy", "label": "Baseline accuracy", "value": round(m["base_acc"], 3), "unit": "", "better": "higher",
             "hint": "Always predicts the most common class - looks respectable on imbalanced data."},
            {"key": "baseline_macro_f1", "label": "Baseline macro F1", "value": round(m["base_f1"], 3), "unit": "", "better": "higher",
             "hint": "Macro F1 averages over classes, exposing the baseline."},
            {"key": "model_accuracy", "label": "Model accuracy", "value": round(m["model_acc"], 3), "unit": "", "better": "higher", "hint": model_name},
            {"key": "model_macro_f1", "label": "Model macro F1", "value": round(m["model_f1"], 3), "unit": "", "better": "higher", "hint": model_name},
            {"key": "weakest_class_f1", "label": f"Weakest class ({worst})", "value": round(float(model_tbl.loc[worst, "f1"]), 3), "unit": "F1",
             "better": "higher", "hint": "Overall accuracy can hide this."},
        ],
        "tables": [
            {"title": "Per-class metrics (model)", "columns": ["class", "precision", "recall", "f1", "support"],
             "rows": [[c, round(float(r.precision), 3), round(float(r.recall), 3), round(float(r.f1), 3), int(r.support)] for c, r in model_tbl.iterrows()]},
            {"title": "Per-class F1 (baseline)", "columns": ["class", "f1", "support"],
             "rows": [[c, round(float(r.f1), 3), int(r.support)] for c, r in base_tbl.iterrows()]},
        ],
        "charts": charts,
        "checks": [
            {"name": "Every class in the evaluation split", "passed": set(y_te) == set(classes),
             "detail": f"{len(set(y_te))} of {len(classes)} classes present in the test set (stratified)."},
            {"name": "Every class in the metrics table", "passed": list(model_tbl.index) == classes, "detail": ", ".join(classes)},
            {"name": "Scaler fit on training data only", "passed": scaler_fit_on_train,
             "detail": "StandardScaler lives inside the Pipeline; its means equal the training-set means."},
        ],
        "notes": [
            "Accuracy rewards the big classes; macro F1 gives every class an equal vote.",
            "SIRA and DERMASON overlap in shape space - expect most confusion between them." ,
            "Synthetic sample: shapes are invented." if is_sample else "Real UCI data - 13,611 beans imaged in Turkey (Koklu & Ozkan, 2020).",
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
    parser.add_argument("--param", action="append", default=[], help="model=logreg|random_forest, test_size=0.25")
    args = parser.parse_args()
    run(args.mode, args.out or f"outputs/{args.mode}", dict(p.split("=", 1) for p in args.param))
