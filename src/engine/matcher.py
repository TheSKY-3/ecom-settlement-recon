"""订单视图装载：三本账 + 底座库 → 按订单号索引的只读内存视图（World）。"""
from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

from src.engine.audit import sha256_of
from src.synth.build_dataset import NATURAL_MISMATCH_SQL


def _read_csv(path: Path) -> list[dict]:
    if not path.is_file():
        raise FileNotFoundError(f"缺少数据文件：{path}（先跑 scripts/build_synthetic.py）")
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _group(rows: list[dict], key: str) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(r[key], []).append(r)
    return out


class World:
    """一次引擎运行的全部输入。只读；分类器不得修改其中任何字段。"""

    def __init__(self, orders, items_by_order, bills_by_order, payments_by_order,
                 refunds_by_order, natural_ids, sources):
        self.orders = orders
        self.items_by_order = items_by_order
        self.bills_by_order = bills_by_order
        self.payments_by_order = payments_by_order
        self.refunds_by_order = refunds_by_order
        self.natural_ids = natural_ids
        self.sources = sources


def load_world(synthetic_dir: Path, db_path: Path) -> World:
    dirty = Path(synthetic_dir) / "dirty"
    bills = _read_csv(dirty / "platform_bills.csv")
    payments = _read_csv(dirty / "order_payments.csv")
    refunds = _read_csv(dirty / "refunds.csv")
    if not Path(db_path).is_file():
        raise FileNotFoundError(f"缺少底座数据库：{db_path}（先跑 scripts/build_db.py）")
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        orders = {r["order_id"]: dict(r) for r in conn.execute(
            "SELECT order_id, order_status, order_approved_at, order_purchase_timestamp FROM orders")}
        items_by_order = _group([dict(r) for r in conn.execute(
            "SELECT order_id, order_item_id, product_id, seller_id, price, freight_value"
            " FROM order_items")], "order_id")
        natural_ids = {r["order_id"] for r in conn.execute(NATURAL_MISMATCH_SQL)}
    finally:
        conn.close()
    sources = {}
    for name, path, rows in (("platform_bills", dirty / "platform_bills.csv", bills),
                             ("order_payments", dirty / "order_payments.csv", payments),
                             ("refunds", dirty / "refunds.csv", refunds)):
        sources[name] = {"path": str(path), "sha256": sha256_of(path), "rows": len(rows)}
    return World(orders, items_by_order, _group(bills, "order_id"),
                 _group(payments, "order_id"), _group(refunds, "order_id"),
                 natural_ids, sources)
