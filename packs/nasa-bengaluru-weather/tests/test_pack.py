import json

import numpy as np
import pytest

import analysis
import load_data


def _fixture():
    return json.loads((load_data.FIXTURE_DIR / "power_bengaluru_sample.json").read_text())


def test_loader_schema():
    df = load_data.load("sample", "bengaluru")
    assert list(df.columns) == list(load_data.PARAMETERS)
    assert df.index.is_monotonic_increasing


def test_signature_trap_fill_value_stays_missing():
    """-999 must become NaN, never a real temperature or rainfall value."""
    raw = _fixture()
    n_fill = sum(v == -999.0 for p in raw["properties"]["parameter"].values() for v in p.values())
    df = load_data.parse_power_json(raw)
    assert int(df.isna().sum().sum()) == n_fill
    assert df.min().min() > -100
    assert np.isnan(df.loc["2022-03-15", "T2M"])


def test_incomplete_month_rainfall_is_excluded():
    df = load_data.load("sample", "bengaluru")
    m = analysis.monthly(df)
    assert np.isnan(m.loc["2023-07-01", "precip_total"])


def test_missing_parameter_is_reported():
    raw = _fixture()
    del raw["properties"]["parameter"]["T2M"]
    with pytest.raises(load_data.DataError, match="T2M"):
        load_data.parse_power_json(raw)


def test_sample_mode_rejects_unavailable_city():
    with pytest.raises(load_data.DataError, match="real mode"):
        load_data.load("sample", "delhi")


def test_query_records_units_and_time_standard():
    q = load_data.build_query(12.9716, 77.5946, "2015-01-01", "2015-01-31")
    assert q["start"] == "20150101" and q["time-standard"] == "LST"
    assert set(q["parameters"].split(",")) == set(load_data.PARAMETERS)


def test_run_sample_end_to_end(tmp_path):
    results = analysis.run("sample", tmp_path, {"compare_city": "chennai"})
    assert all(c["passed"] for c in results["checks"])
    assert any(c["file"] == "city_comparison.png" for c in results["charts"])
    assert (tmp_path / "results.json").exists()
