# Data dictionary — Olist (3 of 9 tables)

All three files are loaded as VARCHAR by DuckDB and cast explicitly in SQL (`try_cast`), so a bad value becomes `NULL` instead of crashing the load.

## `olist_orders_dataset.csv` — grain: **one row per order**
| Column | Type | Description | Key |
|---|---|---|---|
| `order_id` | str | Order identifier | **PK** |
| `customer_id` | str | Customer for this order (one per order) | FK → customers |
| `order_status` | str | delivered, shipped, canceled, invoiced, processing, unavailable, approved, created | |
| `order_purchase_timestamp` | timestamp | When the order was placed | |
| `order_approved_at` | timestamp | Payment approval | may be empty |
| `order_delivered_carrier_date` | timestamp | Handed to the carrier | may be empty |
| `order_delivered_customer_date` | timestamp | Delivered to the customer | **empty unless delivered** |
| `order_estimated_delivery_date` | timestamp | Date promised at purchase (time is 00:00) | |

## `olist_order_items_dataset.csv` — grain: **one row per item in an order**
| Column | Type | Description | Key |
|---|---|---|---|
| `order_id` | str | Order | FK → orders (**many per order**) |
| `order_item_id` | int | 1…n within the order | PK with `order_id` |
| `product_id` | str | Product | |
| `seller_id` | str | Seller | |
| `shipping_limit_date` | timestamp | Seller hand-off deadline | |
| `price` | float (BRL) | Item price | |
| `freight_value` | float (BRL) | Freight allocated to this item | |

## `olist_order_reviews_dataset.csv` — grain: **one row per review** (0…n per order)
| Column | Type | Description | Key |
|---|---|---|---|
| `review_id` | str | Review | not unique in the raw file |
| `order_id` | str | Order | FK → orders (**can repeat**) |
| `review_score` | int | 1–5 stars | |
| `review_comment_title`, `review_comment_message` | str | Free text in Portuguese | often empty |
| `review_creation_date`, `review_answer_timestamp` | timestamp | Survey sent / answered | |

## Derived table `order_facts` (built in `analysis.py`)
One row per order: `n_items`, `items_value`, `freight_value`, average `review_score`, `n_reviews`, `is_delivered`, `is_late` (delivered date > estimated date; `NULL` when not delivered), `delivery_days`.

## Missing-value conventions
Empty strings in timestamps mean "has not happened". `try_cast` turns them into `NULL`. Undelivered orders are excluded from the late rate.

## License
CC BY-NC-SA 4.0 — non-commercial use, share-alike, credit Olist. Raw files stay in `data/raw/` (git-ignored).
