import zipfile

import pandas as pd
import pytest

import analysis
import load_data


def _write_tables(folder, orders, items, reviews):
    pd.DataFrame(orders).to_csv(folder / load_data.FILES["orders"], index=False)
    pd.DataFrame(items).to_csv(folder / load_data.FILES["items"], index=False)
    pd.DataFrame(reviews).to_csv(folder / load_data.FILES["reviews"], index=False)


def _order(oid, delivered, estimated, status="delivered"):
    return {"order_id": oid, "customer_id": "c" + oid, "order_status": status,
            "order_purchase_timestamp": "2018-01-02 10:00:00", "order_approved_at": "2018-01-02 11:00:00",
            "order_delivered_carrier_date": "2018-01-03 10:00:00", "order_delivered_customer_date": delivered,
            "order_estimated_delivery_date": estimated}


def _item(oid, n):
    return {"order_id": oid, "order_item_id": n, "product_id": "p", "seller_id": "s",
            "shipping_limit_date": "", "price": 10.0, "freight_value": 2.0}


def _review(oid, score, rid):
    return {"review_id": rid, "order_id": oid, "review_score": score, "review_comment_title": "",
            "review_comment_message": "", "review_creation_date": "", "review_answer_timestamp": ""}


def test_loader_schema():
    con = load_data.connect("sample")
    for table, cols in load_data.COLUMNS.items():
        got = [r[0] for r in con.execute(f"describe {table}").fetchall()]
        assert set(cols) <= set(got)


def test_signature_trap_two_item_order_counts_once(tmp_path):
    """An order with two items still contributes exactly one order to delivery KPIs."""
    _write_tables(
        tmp_path,
        orders=[_order("A", "2018-01-20 12:00:00", "2018-01-15 00:00:00"),  # late
                _order("B", "2018-01-10 12:00:00", "2018-01-15 00:00:00")],  # on time
        items=[_item("A", 1), _item("A", 2), _item("B", 1)],
        reviews=[_review("A", 1, "r1"), _review("A", 2, "r2"), _review("B", 5, "r3")],
    )
    con = load_data.connect("custom", tmp_path)
    facts = analysis.build_order_facts(con)
    assert len(facts) == 2
    k = analysis.kpis(con)
    assert k["orders"] == 2 and k["delivered"] == 2
    assert k["late_rate"] == pytest.approx(0.5)  # naive join would say 2 of 3 rows late
    naive = con.execute(analysis.NAIVE_SQL).df().iloc[0]
    assert naive["naive_order_count"] == 5  # 2 items x 2 reviews for A + 1 for B
    assert facts.set_index("order_id").loc["A", "n_items"] == 2


def test_duplicate_orders_rejected(tmp_path):
    _write_tables(tmp_path, [_order("A", "", "2018-01-15 00:00:00")] * 2, [_item("A", 1)], [_review("A", 3, "r")])
    with pytest.raises(load_data.DataError, match="one row per order_id"):
        load_data.connect("custom", tmp_path)


def test_real_mode_missing_files_explains_recovery(monkeypatch, tmp_path):
    monkeypatch.setattr(load_data, "RAW_DIR", tmp_path)
    with pytest.raises(load_data.DataError, match="kaggle.com"):
        load_data.connect("real", tmp_path, fetch_if_missing=False)


def test_import_from_zip_ignores_paths(monkeypatch, tmp_path):
    raw = tmp_path / "raw"
    monkeypatch.setattr(load_data, "RAW_DIR", raw)
    monkeypatch.setattr(load_data, "SOURCE_META", raw / "source.json")
    archive = tmp_path / "olist.zip"
    with zipfile.ZipFile(archive, "w") as z:
        for name in load_data.FILES.values():
            z.write(load_data.FIXTURE_DIR / f"sample_{name}", f"../../evil/{name}")
        z.writestr("other.csv", "x")
    found = load_data.import_files(archive)
    assert sorted(found) == sorted(load_data.FILES.values())
    assert (raw / "source.json").exists()
    assert not (tmp_path / "evil").exists()


def test_run_sample_end_to_end(tmp_path):
    results = analysis.run("sample", tmp_path)
    assert all(c["passed"] for c in results["checks"])
    for chart in results["charts"]:
        assert (tmp_path / chart["file"]).exists()
