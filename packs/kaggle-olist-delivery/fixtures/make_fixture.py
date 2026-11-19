"""Regenerate the synthetic Olist-format CSVs (orders, order items, reviews).

Tricky cases built in:
* ~15 % of orders have 2-4 items -> a naive orders-items join counts them several times.
* some orders have 2 reviews, some none -> joining reviews multiplies rows again.
* canceled / shipped orders have no delivery date -> they are not "on time" or "late".
"""
from pathlib import Path

import numpy as np
import pandas as pd

rng = np.random.default_rng(5)
HERE = Path(__file__).resolve().parent
N = 600
fmt = "%Y-%m-%d %H:%M:%S"

purchase = pd.to_datetime("2017-01-01") + pd.to_timedelta(np.sort(rng.uniform(0, 540, N)), unit="D")
purchase = purchase + pd.to_timedelta(rng.integers(0, 86400, N), unit="s")
status = rng.choice(["delivered", "shipped", "canceled", "invoiced"], p=[0.93, 0.03, 0.025, 0.015], size=N)
est_days = rng.integers(15, 35, N)
estimated = (purchase + pd.to_timedelta(est_days, unit="D")).normalize()
# Late share rises around the end-of-year rush.
rush = ((purchase.month == 11) | (purchase.month == 12) | ((purchase.month == 3) & (purchase.year == 2018)))
late = rng.random(N) < np.where(rush, 0.22, 0.06)
actual_days = np.where(late, est_days + rng.integers(1, 15, N), est_days - rng.integers(1, 14, N))
delivered = purchase + pd.to_timedelta(actual_days, unit="D") + pd.to_timedelta(rng.integers(0, 50000, N), unit="s")
order_ids = [f"ord{idx:05d}{rng.integers(1e6):06d}" for idx in range(N)]

orders = pd.DataFrame({
    "order_id": order_ids,
    "customer_id": [f"cus{rng.integers(1e9):09d}" for _ in range(N)],
    "order_status": status,
    "order_purchase_timestamp": purchase.strftime(fmt),
    "order_approved_at": (purchase + pd.Timedelta(hours=2)).strftime(fmt),
    "order_delivered_carrier_date": np.where(status == "canceled", "", (purchase + pd.Timedelta(days=2)).strftime(fmt)),
    "order_delivered_customer_date": np.where(status == "delivered", delivered.strftime(fmt), ""),
    "order_estimated_delivery_date": estimated.strftime(fmt),
})

item_rows = []
for oid in order_ids:
    n_items = rng.choice([1, 2, 3, 4], p=[0.85, 0.1, 0.035, 0.015])
    for k in range(1, n_items + 1):
        item_rows.append({"order_id": oid, "order_item_id": k, "product_id": f"prd{rng.integers(400):04d}",
                          "seller_id": f"sel{rng.integers(60):03d}", "shipping_limit_date": "",
                          "price": round(float(rng.lognormal(4.2, 0.7)), 2), "freight_value": round(float(rng.uniform(7, 40)), 2)})
items = pd.DataFrame(item_rows)

review_rows = []
for i, (oid, st) in enumerate(zip(order_ids, status)):
    n_rev = rng.choice([0, 1, 2], p=[0.03, 0.92, 0.05])
    for _ in range(n_rev):
        score = int(np.clip(rng.normal(2.2 if late[i] else 4.4, 1.0), 1, 5).round()) if st == "delivered" else int(rng.integers(1, 4))
        review_rows.append({"review_id": f"rev{rng.integers(1e9):09d}", "order_id": oid, "review_score": score,
                            "review_comment_title": "", "review_comment_message": "",
                            "review_creation_date": (delivered[i] + pd.Timedelta(days=1)).strftime(fmt),
                            "review_answer_timestamp": (delivered[i] + pd.Timedelta(days=2)).strftime(fmt)})
reviews = pd.DataFrame(review_rows)

orders.to_csv(HERE / "sample_olist_orders_dataset.csv", index=False)
items.to_csv(HERE / "sample_olist_order_items_dataset.csv", index=False)
reviews.to_csv(HERE / "sample_olist_order_reviews_dataset.csv", index=False)
print(f"orders={len(orders)} items={len(items)} reviews={len(reviews)}")
