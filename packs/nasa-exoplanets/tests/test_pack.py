import pandas as pd
import pytest

import analysis
import load_data


def test_loader_schema():
    df = load_data.load("sample")
    assert list(df.columns) == list(load_data.COLUMNS)
    assert df["pl_name"].is_unique


def test_signature_trap_missing_radii_reported_before_filtering(tmp_path):
    """The report must describe the full catalog, not the filtered scatter-plot subset."""
    catalog = load_data.load("sample")
    expected_missing = int(catalog["pl_rade"].isna().sum())
    assert expected_missing > 0, "fixture must contain planets without radii"
    results = analysis.run("sample", tmp_path)
    table = next(t for t in results["tables"] if t["title"].startswith("Missingness"))
    row = next(r for r in table["rows"] if r[0] == "pl_rade")
    assert row[1] == expected_missing
    assert row[2] == len(catalog)
    plottable = next(m for m in results["metrics"] if m["key"] == "plottable")["value"]
    assert plottable == len(catalog.dropna(subset=["pl_rade", "pl_orbper"]))
    assert plottable < len(catalog)


def test_duplicate_planet_rejected():
    df = pd.read_csv(load_data.FIXTURE_FILE)
    df = pd.concat([df, df.head(1)])
    with pytest.raises(load_data.DataError, match="unique"):
        load_data.validate(df)


def test_query_records_columns():
    assert "pscomppars" in load_data.QUERY
    assert "discoverymethod" in load_data.query_url()


def test_charts_written(tmp_path):
    results = analysis.run("sample", tmp_path)
    assert all(c["passed"] for c in results["checks"])
    for chart in results["charts"]:
        assert (tmp_path / chart["file"]).exists()
