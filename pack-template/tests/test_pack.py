import analysis
import load_data


def test_loader_schema():
    df = load_data.load("sample")
    assert set(load_data.EXPECTED_COLUMNS) <= set(df.columns)


def test_signature_trap(tmp_path):
    """TODO: one regression test for the mistake this pack teaches."""
    results = analysis.run("sample", tmp_path)
    assert all(c["passed"] for c in results["checks"])
