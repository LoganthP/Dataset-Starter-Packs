import json

import pandas as pd
import pytest

import analysis
import load_data


def test_loader_schema():
    df = load_data.load("sample")
    for col in load_data.EXPECTED_COLUMNS:
        assert col in df.columns
    assert (df["casual"] + df["registered"] == df["cnt"]).all()
    assert df["timestamp"].is_monotonic_increasing


def test_missing_column_is_reported():
    df = pd.read_csv(load_data.FIXTURE_FILE).drop(columns=["cnt"])
    with pytest.raises(load_data.DataError, match="cnt"):
        load_data.validate(df)


def test_real_mode_without_file_gives_recovery_hint(monkeypatch, tmp_path):
    monkeypatch.setattr(load_data, "RAW_FILE", tmp_path / "hour.csv")
    with pytest.raises(load_data.DataError, match="hour.csv"):
        load_data.load("real", fetch_if_missing=False)


def test_signature_trap_no_leakage_and_time_ordered_holdout():
    """casual/registered never enter the features; holdout starts after training."""
    frame = analysis.build_features(load_data.load("sample"))
    train, test, _ = analysis.chronological_split(frame, 0.2)
    X = analysis.feature_matrix(train)
    assert not set(load_data.LEAKY_COLUMNS) & set(X.columns)
    assert "cnt" not in X.columns
    assert train["timestamp"].max() < test["timestamp"].min()


def test_feature_matrix_rejects_leaky_columns(monkeypatch):
    frame = analysis.build_features(load_data.load("sample"))
    monkeypatch.setattr(analysis, "FEATURES", analysis.FEATURES + ["casual"])
    with pytest.raises(AssertionError, match="Leakage"):
        analysis.feature_matrix(frame)


def test_lags_respect_missing_hours():
    frame = analysis.build_features(load_data.load("sample"))
    raw = load_data.load("sample").set_index("timestamp")["cnt"]
    row = frame.iloc[500]
    prev = row["timestamp"] - pd.Timedelta(hours=1)
    expected = raw.get(prev)
    if expected is None:
        assert pd.isna(row["cnt_lag1"])
    else:
        assert row["cnt_lag1"] == expected


def test_run_sample_end_to_end(tmp_path):
    results = analysis.run("sample", tmp_path)
    assert results["is_sample"] is True
    assert all(check["passed"] for check in results["checks"])
    saved = json.loads((tmp_path / "results.json").read_text())
    assert saved["metrics"][0]["key"] == "baseline_mae"
    for chart in saved["charts"]:
        assert (tmp_path / chart["file"]).exists()
