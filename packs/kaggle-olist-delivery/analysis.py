"""Delivery analytics on Olist with DuckDB SQL - and the join that inflates your KPIs.

    python analysis.py --mode sample
    python analysis.py --mode real
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

import pandas as pd

import load_data

PACK = "kaggle-olist-delivery"
COLORS = {"volume": "#A5B4FC", "late": "#EF4444", "ontime": "#22C55E", "naive": "#F97316", "correct": "#6366F1"}

GRAIN_SQL = """
select
  (select count(*) from orders)                                   as order_rows,
  (select count(distinct order_id) from orders)                   as distinct_orders,
  (select count(*) from items)                                    as item_rows,
  (select count(*) from (select order_id from items group by 1 having count(*) > 1)) as multi_item_orders,
  (select count(*) from reviews)                                  as review_rows,
  (select count(*) from (select order_id from reviews group by 1 having count(*) > 1)) as multi_review_orders
"""

# The tempting query: join everything at once, then count rows as if they were orders.
NAIVE_SQL = """
select
  count(*)                                                      as naive_order_count,
  count(distinct o.order_id)                                    as true_order_count,
  avg(case when try_cast(o.order_delivered_customer_date as timestamp)::date
               > try_cast(o.order_estimated_delivery_date as timestamp)::date then 1.0 else 0.0 end)
      filter (where o.order_status = 'delivered' and o.order_delivered_customer_date <> '')
                                                                as naive_late_rate,
  avg(try_cast(r.review_score as integer))                      as naive_avg_review
from orders o
join items i on i.order_id = o.order_id
left join reviews r on r.order_id = o.order_id
"""

# The correct approach: aggregate each child table to ONE row per order first, then join.
ORDER_FACTS_SQL = """
create or replace table order_facts as
with item_agg as (
  select order_id, count(*) as n_items, sum(try_cast(price as double)) as items_value,
         sum(try_cast(freight_value as double)) as freight_value
  from items group by order_id
),
review_agg as (
  select order_id, avg(try_cast(review_score as integer)) as review_score, count(*) as n_reviews
  from reviews group by order_id
),
base as (
  select order_id, order_status,
         try_cast(order_purchase_timestamp as timestamp)      as purchased_at,
         try_cast(order_delivered_customer_date as timestamp) as delivered_at,
         try_cast(order_estimated_delivery_date as timestamp) as estimated_at
  from orders
)
select b.*,
       coalesce(i.n_items, 0) as n_items, i.items_value, i.freight_value,
       r.review_score, coalesce(r.n_reviews, 0) as n_reviews,
       (b.order_status = 'delivered' and b.delivered_at is not null) as is_delivered,
       case when b.order_status = 'delivered' and b.delivered_at is not null
            then b.delivered_at::date > b.estimated_at::date end as is_late,
       date_diff('day', b.purchased_at, b.delivered_at) as delivery_days
from base b
left join item_agg i using (order_id)
left join review_agg r using (order_id)
"""

MONTHLY_SQL = """
select date_trunc('month', purchased_at)::date as month,
       count(*)                                        as orders,
       count(*) filter (where is_delivered)            as delivered,
       avg(case when is_late then 1.0 else 0.0 end) filter (where is_delivered) as late_rate,
       avg(review_score)                               as avg_review
from order_facts
where purchased_at is not null
group by 1 order by 1
"""

REVIEW_BY_LATENESS_SQL = """
select case when is_late then 'late' else 'on time' end as delivery,
       round(review_score) as score, count(*) as orders
from order_facts
where is_delivered and review_score is not null
group by 1, 2 order by 1, 2
"""

KPI_SQL = """
select count(*) as orders,
       count(*) filter (where is_delivered) as delivered,
       avg(case when is_late then 1.0 else 0.0 end) filter (where is_delivered) as late_rate,
       avg(review_score) filter (where is_delivered and not is_late) as review_on_time,
       avg(review_score) filter (where is_delivered and is_late) as review_late,
       median(delivery_days) filter (where is_delivered) as median_delivery_days
from order_facts
"""


def build_order_facts(con) -> pd.DataFrame:
    con.execute(ORDER_FACTS_SQL)
    return con.execute("select * from order_facts").df()


def kpis(con) -> dict:
    return con.execute(KPI_SQL).df().iloc[0].to_dict()


def _stamp(fig, is_sample):
    if is_sample:
        fig.text(0.99, 0.01, "SYNTHETIC SAMPLE - invented orders", ha="right", va="bottom", fontsize=8, color="#F97316")


def plot_monthly(m: pd.DataFrame, out: Path, is_sample: bool) -> str:
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.bar(m["month"], m["orders"], width=20, color=COLORS["volume"], label="Orders")
    ax.set(ylabel="Orders per month", title="Order volume and late-delivery rate by purchase month")
    ax2 = ax.twinx()
    ax2.plot(m["month"], m["late_rate"] * 100, color=COLORS["late"], marker="o", lw=2, label="Late rate")
    ax2.set_ylabel("Late deliveries (%)", color=COLORS["late"])
    ax2.set_ylim(0, max(30, float((m["late_rate"] * 100).max() or 0) * 1.2))
    ax.grid(alpha=0.25, axis="y")
    lines = ax.get_legend_handles_labels()[0] + ax2.get_legend_handles_labels()[0]
    ax.legend(lines, ["Orders", "Late rate"], frameon=False, loc="upper left")
    fig.autofmt_xdate()
    _stamp(fig, is_sample)
    fig.tight_layout()
    fig.savefig(out / "monthly_volume_late_rate.png", dpi=130)
    plt.close(fig)
    return "monthly_volume_late_rate.png"


def plot_reviews(r: pd.DataFrame, out: Path, is_sample: bool) -> str:
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 4))
    pivot = r.pivot_table(index="score", columns="delivery", values="orders", fill_value=0)
    share = pivot / pivot.sum() * 100
    width = 0.38
    x = share.index.to_numpy()
    if "on time" in share:
        ax.bar(x - width / 2, share["on time"], width, color=COLORS["ontime"], label="On time")
    if "late" in share:
        ax.bar(x + width / 2, share["late"], width, color=COLORS["late"], label="Late")
    ax.set(xlabel="Review score", ylabel="% of orders", title="Review scores: late vs. on-time deliveries")
    ax.set_xticks([1, 2, 3, 4, 5])
    ax.grid(alpha=0.25, axis="y")
    ax.legend(frameon=False)
    _stamp(fig, is_sample)
    fig.tight_layout()
    fig.savefig(out / "reviews_by_lateness.png", dpi=130)
    plt.close(fig)
    return "reviews_by_lateness.png"


def plot_naive_vs_correct(naive: dict, correct: dict, out: Path, is_sample: bool) -> str:
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(9, 3.6))
    labels = ["Naive join", "Order grain"]
    axes[0].bar(labels, [naive["naive_order_count"], correct["orders_with_items"]], color=[COLORS["naive"], COLORS["correct"]])
    axes[0].set_title("'Orders' counted")
    axes[1].bar(labels, [naive["naive_late_rate"] * 100, correct["late_rate"] * 100], color=[COLORS["naive"], COLORS["correct"]])
    axes[1].set_title("Late-delivery rate (%)")
    for ax in axes:
        ax.grid(alpha=0.25, axis="y")
        for p in ax.patches:
            ax.annotate(f"{p.get_height():,.1f}" if p.get_height() < 100 else f"{p.get_height():,.0f}",
                        (p.get_x() + p.get_width() / 2, p.get_height()), ha="center", va="bottom", fontsize=9)
    fig.suptitle("Joining before aggregating inflates order-level metrics")
    _stamp(fig, is_sample)
    fig.tight_layout()
    fig.savefig(out / "naive_vs_correct.png", dpi=130)
    plt.close(fig)
    return "naive_vs_correct.png"


def run(mode: str = "sample", out_dir: str | Path = "outputs/sample", params: dict | None = None, data_dir: Path | None = None) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    is_sample = mode == "sample"

    print(f"[1/5] Opening DuckDB over {mode} CSVs", flush=True)
    con = load_data.connect(mode, data_dir)

    print("[2/5] Checking the grain of each table", flush=True)
    grain = con.execute(GRAIN_SQL).df().iloc[0].to_dict()
    print(f"      {grain['multi_item_orders']} orders have several items; {grain['multi_review_orders']} have several reviews", flush=True)

    print("[3/5] Naive join vs. aggregate-then-join", flush=True)
    naive = con.execute(NAIVE_SQL).df().iloc[0].to_dict()
    facts = build_order_facts(con)
    k = kpis(con)
    orders_with_items = int((facts["n_items"] > 0).sum())
    distinct_after = int(facts["order_id"].nunique())

    print("[4/5] Monthly KPIs and review analysis", flush=True)
    monthly = con.execute(MONTHLY_SQL).df()
    reviews = con.execute(REVIEW_BY_LATENESS_SQL).df()
    charts = [
        {"file": plot_monthly(monthly, out, is_sample), "title": "Volume and late rate by month",
         "caption": "Late deliveries cluster around demand spikes."},
        {"file": plot_reviews(reviews, out, is_sample), "title": "Reviews: late vs. on time",
         "caption": "Late orders collect far more 1-star reviews."},
        {"file": plot_naive_vs_correct(naive, {"orders_with_items": orders_with_items, "late_rate": k["late_rate"]}, out, is_sample),
         "title": "Naive vs. correct grain", "caption": "Same data, different answer - because rows are not orders."},
    ]

    print("[5/5] Writing results", flush=True)
    inflation = naive["naive_order_count"] / orders_with_items - 1 if orders_with_items else 0
    results = {
        "pack": PACK,
        "mode": mode,
        "is_sample": is_sample,
        "generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "headline": f"{k['late_rate'] * 100:.1f}% of delivered orders arrived late; late orders average "
                    f"{k['review_late']:.2f}★ vs. {k['review_on_time']:.2f}★ on time. A naive join over-counts orders by {inflation * 100:.0f}%.",
        "metrics": [
            {"key": "orders", "label": "Orders", "value": int(k["orders"]), "unit": "", "better": None, "hint": "Distinct order_id in orders."},
            {"key": "late_rate", "label": "Late-delivery rate", "value": round(float(k["late_rate"]) * 100, 2), "unit": "%", "better": "lower",
             "hint": "Delivered after the estimated date, among delivered orders."},
            {"key": "review_on_time", "label": "Avg review (on time)", "value": round(float(k["review_on_time"]), 2), "unit": "★", "better": "higher", "hint": ""},
            {"key": "review_late", "label": "Avg review (late)", "value": round(float(k["review_late"]), 2), "unit": "★", "better": "higher", "hint": ""},
            {"key": "naive_inflation_pct", "label": "Naive join inflation", "value": round(inflation * 100, 1), "unit": "%", "better": "lower",
             "hint": "Extra 'orders' counted when items and reviews are joined before aggregating."},
            {"key": "median_delivery_days", "label": "Median delivery time", "value": float(k["median_delivery_days"]), "unit": "days", "better": "lower", "hint": ""},
        ],
        "tables": [
            {"title": "Table grain check", "columns": ["measure", "value"], "rows": [[key, int(v)] for key, v in grain.items()]},
            {"title": "Naive join vs. order grain", "columns": ["measure", "naive join", "order grain"], "rows": [
                ["orders counted", int(naive["naive_order_count"]), orders_with_items],
                ["late rate (%)", round(float(naive["naive_late_rate"]) * 100, 2), round(float(k["late_rate"]) * 100, 2)],
                ["avg review", round(float(naive["naive_avg_review"]), 3),
                 round(float(facts["review_score"].mean()), 3)]]},
            {"title": "Monthly KPIs", "columns": ["month", "orders", "delivered", "late_rate_pct", "avg_review"],
             "rows": [[str(r.month)[:7], int(r.orders), int(r.delivered),
                       round(float(r.late_rate) * 100, 2) if pd.notna(r.late_rate) else None,
                       round(float(r.avg_review), 2) if pd.notna(r.avg_review) else None] for r in monthly.itertuples()]},
            {"title": "SQL: order_facts (aggregate first, then join)", "columns": ["sql"], "rows": [[ORDER_FACTS_SQL.strip()]]},
        ],
        "charts": charts,
        "checks": [
            {"name": "One row per order after joins", "passed": distinct_after == len(facts) == int(grain["distinct_orders"]),
             "detail": f"order_facts has {len(facts):,} rows and {distinct_after:,} distinct orders."},
            {"name": "Multi-item orders counted once", "passed": bool(facts.loc[facts["n_items"] > 1, "order_id"].is_unique),
             "detail": f"{grain['multi_item_orders']} multi-item orders each contribute exactly one row to delivery KPIs."},
            {"name": "Undelivered orders excluded from late rate", "passed": bool(facts.loc[~facts["is_delivered"], "is_late"].isna().all()),
             "detail": "Canceled/shipped orders are neither late nor on time."},
        ],
        "notes": [
            "Grain: orders = 1 row/order; items = 1 row/item; reviews = 0..n rows/order. Aggregate children before joining.",
            "Synthetic sample - invented orders." if is_sample else
            "Olist data is CC BY-NC-SA 4.0: non-commercial, share-alike, credit Olist. Keep raw files out of Git.",
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
    parser.add_argument("--param", action="append", default=[])
    args = parser.parse_args()
    run(args.mode, args.out or f"outputs/{args.mode}", dict(p.split("=", 1) for p in args.param))
