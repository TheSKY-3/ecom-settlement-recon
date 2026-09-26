#!/usr/bin/env python3
"""把 data/raw 的 Olist CSV 装入 SQLite（data/olist.db），DDL 来自 sql/01_schema.sql。

仅用标准库。原始层不设唯一约束，保证 CSV 每一行都进入库中（重复键是待测量的异常，
不允许在加载层被静默丢弃）。加载后做行数与金额总和校验。
"""
import csv
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
SCHEMA = ROOT / "sql" / "01_schema.sql"
DB = ROOT / "data" / "olist.db"

# table -> (csv 文件名, [(列名, 类型), ...])；类型：TEXT / INT / REAL（日期按 TEXT 存）
TABLES = {
    "orders": ("olist_orders_dataset.csv", [
        ("order_id", "TEXT"), ("customer_id", "TEXT"), ("order_status", "TEXT"),
        ("order_purchase_timestamp", "TEXT"), ("order_approved_at", "TEXT"),
        ("order_delivered_carrier_date", "TEXT"), ("order_delivered_customer_date", "TEXT"),
        ("order_estimated_delivery_date", "TEXT")]),
    "order_items": ("olist_order_items_dataset.csv", [
        ("order_id", "TEXT"), ("order_item_id", "INT"), ("product_id", "TEXT"),
        ("seller_id", "TEXT"), ("shipping_limit_date", "TEXT"),
        ("price", "REAL"), ("freight_value", "REAL")]),
    "order_payments": ("olist_order_payments_dataset.csv", [
        ("order_id", "TEXT"), ("payment_sequential", "INT"), ("payment_type", "TEXT"),
        ("payment_installments", "INT"), ("payment_value", "REAL")]),
    "order_reviews": ("olist_order_reviews_dataset.csv", [
        ("review_id", "TEXT"), ("order_id", "TEXT"), ("review_score", "INT"),
        ("review_comment_title", "TEXT"), ("review_comment_message", "TEXT"),
        ("review_creation_date", "TEXT"), ("review_answer_timestamp", "TEXT")]),
    "customers": ("olist_customers_dataset.csv", [
        ("customer_id", "TEXT"), ("customer_unique_id", "TEXT"),
        ("customer_zip_code_prefix", "INT"), ("customer_city", "TEXT"),
        ("customer_state", "TEXT")]),
    "sellers": ("olist_sellers_dataset.csv", [
        ("seller_id", "TEXT"), ("seller_zip_code_prefix", "INT"),
        ("seller_city", "TEXT"), ("seller_state", "TEXT")]),
    "products": ("olist_products_dataset.csv", [
        ("product_id", "TEXT"), ("product_category_name", "TEXT"),
        ("product_name_lenght", "INT"), ("product_description_lenght", "INT"),
        ("product_photos_qty", "INT"), ("product_weight_g", "INT"),
        ("product_length_cm", "INT"), ("product_height_cm", "INT"),
        ("product_width_cm", "INT")]),
    "geolocation": ("olist_geolocation_dataset.csv", [
        ("geolocation_zip_code_prefix", "INT"), ("geolocation_lat", "REAL"),
        ("geolocation_lng", "REAL"), ("geolocation_city", "TEXT"),
        ("geolocation_state", "TEXT")]),
    "product_category_translation": ("product_category_name_translation.csv", [
        ("product_category_name", "TEXT"), ("product_category_name_english", "TEXT")]),
}

# 金额校验和：列 -> (表)
MONEY_CHECKS = {"price": "order_items", "freight_value": "order_items",
                "payment_value": "order_payments"}


def convert(val, typ):
    if val is None or val == "":
        return None
    if typ == "INT":
        return int(val)
    if typ == "REAL":
        return float(val)
    return val


def main():
    t0 = time.time()
    if not any(RAW.glob("*.csv")):
        sys.exit(f"[FAIL] {RAW} 下没有 CSV，请先放入 Olist 9 张表")
    if DB.exists():
        DB.unlink()

    conn = sqlite3.connect(DB)
    conn.execute("PRAGMA journal_mode=OFF")
    conn.execute("PRAGMA synchronous=OFF")
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))

    py_sums = {}
    print(f"{'table':34s} {'csv_rows':>9s} {'db_rows':>9s}  ok")
    for table, (fname, cols) in TABLES.items():
        col_names = [c for c, _ in cols]
        ins = (f"INSERT INTO {table} ({', '.join(col_names)}) "
               f"VALUES ({', '.join('?' * len(cols))})")
        n = 0
        batch = []
        with (RAW / fname).open(newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            missing = [c for c in col_names if c not in (reader.fieldnames or [])]
            if missing:
                sys.exit(f"[FAIL] {fname} 缺少列: {missing}")
            for row in reader:
                rec = []
                for c, typ in cols:
                    raw = row.get(c)
                    try:
                        rec.append(convert(raw, typ))
                    except (TypeError, ValueError) as e:
                        sys.exit(f"[FAIL] {fname} 第 {reader.line_num} 行 {c}={raw!r}: {e}")
                    if c in MONEY_CHECKS and MONEY_CHECKS[c] == table:
                        py_sums[c] = py_sums.get(c, 0.0) + (
                            float(raw) if raw not in (None, "") else 0.0)
                batch.append(rec)
                n += 1
                if len(batch) >= 10000:
                    conn.executemany(ins, batch)
                    batch = []
        if batch:
            conn.executemany(ins, batch)
        conn.commit()
        db_n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        flag = "OK" if db_n == n else "MISMATCH"
        print(f"{table:34s} {n:9d} {db_n:9d}  {flag}")
        if flag != "OK":
            sys.exit(f"[FAIL] {table} 行数不一致")

    print("-" * 60)
    fail = False
    for col, table in MONEY_CHECKS.items():
        db_sum = conn.execute(f"SELECT ROUND(SUM({col}), 2) FROM {table}").fetchone()[0]
        ok = abs(db_sum - round(py_sums[col], 2)) < 0.05
        fail |= not ok
        print(f"checksum {table}.{col:14s} csv={py_sums[col]:14.2f} "
              f"db={db_sum:14.2f}  {'OK' if ok else 'MISMATCH'}")

    size_mb = DB.stat().st_size / 1e6
    print(f"\n[OK] {DB} ({size_mb:.1f} MB, sqlite {sqlite3.sqlite_version}) "
          f"in {time.time() - t0:.1f}s")
    conn.close()
    if fail:
        sys.exit("[FAIL] 金额校验和不一致")


if __name__ == "__main__":
    main()
