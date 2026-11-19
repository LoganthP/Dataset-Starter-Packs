import pandas as pd
import pytest

import analysis
import load_data


def test_loader_schema():
    df = load_data.load("sample")
    assert list(df.columns) == load_data.FEATURES + [load_data.TARGET]
    assert set(df[load_data.TARGET]) == load_data.EXPECTED_CLASSES


def test_header_aliases_are_normalised():
    df = pd.read_csv(load_data.FIXTURE_FILE).rename(columns={"AspectRation": "AspectRatio", "roundness": "Roundness"})
    assert "AspectRation" in load_data.validate(df).columns


def test_unknown_class_rejected():
    df = pd.read_csv(load_data.FIXTURE_FILE)
    df.loc[0, "Class"] = "PINTO"
    with pytest.raises(load_data.DataError, match="PINTO"):
        load_data.validate(df)


def test_signature_trap_every_class_evaluated(tmp_path):
    """Every expected class is in the evaluation split and in the metrics table."""
    df = load_data.load("sample")
    _, _, _, y_te = analysis.split(df, 0.25)
    assert set(y_te) == load_data.EXPECTED_CLASSES
    results = analysis.run("sample", tmp_path)
    table = next(t for t in results["tables"] if t["title"].startswith("Per-class metrics"))
    assert {row[0] for row in table["rows"]} == load_data.EXPECTED_CLASSES
    assert all(row[4] > 0 for row in table["rows"])


def test_scaler_fit_on_training_only(tmp_path):
    results = analysis.run("sample", tmp_path, {"model": "logreg"})
    check = next(c for c in results["checks"] if c["name"].startswith("Scaler"))
    assert check["passed"]


def test_macro_f1_exposes_majority_baseline(tmp_path):
    results = analysis.run("sample", tmp_path)
    metric = {m["key"]: m["value"] for m in results["metrics"]}
    assert metric["baseline_accuracy"] > 2 * metric["baseline_macro_f1"]
    assert metric["model_macro_f1"] > metric["baseline_macro_f1"]
