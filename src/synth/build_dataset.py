"""编排器：从 data/olist.db 读干净底座 → 生成干净三本账 → 六类埋雷 → 写 data/synthetic/。

产出自校验（行数守恒、标准答案可解析、自然差异单绝不被埋雷）不过就报错，
绝不带病输出——评测集冻结的前提是产物可信。
"""

import csv
import random
from collections import Counter
from pathlib import Path

from src.synth import config
from src.synth.bills import BILL_COLUMNS, generate_bills
from src.synth.ground_truth import read as read_gt
from src.synth.ground_truth import write as write_gt
from src.synth.injectors import (allocate_pools, inject_amount_mismatch,
                                 inject_duplicate, inject_refund_missing,
                                 inject_single_sided,
                                 inject_status_inconsistency,
                                 inject_version_diff)
from src.synth.refunds import REFUND_COLUMNS, generate_refunds

PAYMENT_COLUMNS = ["order_id", "payment_sequential", "payment_type",
                   "payment_installments", "payment_value"]

NATURAL_MISMATCH_SQL = """
SELECT o.order_id FROM orders o
JOIN (SELECT order_id, ROUND(SUM(price)+SUM(freight_value),2) t
      FROM order_items GROUP BY 1) i ON o.order_id = i.order_id
JOIN (SELECT order_id, ROUND(SUM(payment_value),2) v
      FROM order_payments GROUP BY 1) p ON o.order_id = p.order_id
WHERE ABS(p.v - i.t) >= 0.005
"""

DEFAULT_COUNTS = {
    "drop_bill": config.SINGLE_DROP_BILL, "orphan": config.SINGLE_ORPHAN_BILL,
    "drop_payment": config.SINGLE_DROP_PAYMENT,
    "wrong_rate": config.AMOUNT_WRONG_RATE,
    "missing_freight": config.AMOUNT_MISSING_FREIGHT,
    "status_rebill": config.STATUS_REBILL,
    "refund_missing": config.REFUND_MISSING,
    "duplicate": config.DUPLICATE_BILL, "version_diff": config.VERSION_DIFF,
}


def _query(conn, sql: str) -> list[dict]:
    cur = conn.execute(sql)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def load_base(conn) -> dict:
    orders = _query(conn, "SELECT * FROM orders ORDER BY order_id")
    items = _query(conn, "SELECT * FROM order_items ORDER BY order_id, order_item_id")
    payments = _query(conn, "SELECT * FROM order_payments "
                            "ORDER BY order_id, payment_sequential")
    items_by_order: dict[str, list[dict]] = {}
    for item in items:
        items_by_order.setdefault(item["order_id"], []).append(item)
    pay_sum: dict[str, float] = {}
    for p in payments:
        pay_sum[p["order_id"]] = round(
            pay_sum.get(p["order_id"], 0.0) + float(p["payment_value"]), 2)
    natural = {r["order_id"] for r in _query(conn, NATURAL_MISMATCH_SQL)}
    return {"orders": orders, "items_by_order": items_by_order,
            "payments": payments, "pay_sum_by_order": pay_sum,
            "natural_mismatch_ids": natural}


def _write_csv(rows: list[dict], columns: list[str], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def _read_csv(path: Path) -> list[dict]:
    with Path(path).open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def build(conn, out_dir, counts: dict | None = None, seed: int | None = None) -> dict:
    counts = dict(DEFAULT_COUNTS, **(counts or {}))
    rng = random.Random(config.SEED if seed is None else seed)
    base = load_base(conn)
    orders = base["orders"]
    orders_index = {o["order_id"]: o for o in orders}

    clean_bills = generate_bills(orders, base["items_by_order"])
    clean_refunds = generate_refunds(orders, base["pay_sum_by_order"])

    natural = base["natural_mismatch_ids"]
    active_ids = [b["order_id"] for b in clean_bills if b["order_id"] not in natural]
    rebill_ids = [o["order_id"] for o in orders
                  if o["order_status"] in config.NO_BILL_STATUSES
                  and o["order_id"] in base["items_by_order"]
                  and o["order_id"] not in natural]
    refund_ids = [r["order_id"] for r in clean_refunds if r["order_id"] not in natural]
    nonzero_freight = {oid for oid, items in base["items_by_order"].items()
                       if round(sum(float(i["freight_value"]) for i in items), 2) > 0}

    pools = allocate_pools(rng, active_ids, rebill_ids, refund_ids,
                           orders_index, counts, nonzero_freight_ids=nonzero_freight)

    bills = [dict(b) for b in clean_bills]
    dirty_payments = [dict(p) for p in base["payments"]]
    dirty_refunds = [dict(r) for r in clean_refunds]
    gt: list[dict] = []
    inject_single_sided(bills, dirty_payments, orders_index, pools, gt)
    inject_amount_mismatch(bills, pools, gt)
    inject_status_inconsistency(bills, orders_index, base["items_by_order"], pools, gt)
    inject_refund_missing(dirty_refunds, pools, gt)
    inject_duplicate(bills, pools, gt)
    inject_version_diff(bills, pools, gt)

    out = Path(out_dir)
    _write_csv(clean_bills, BILL_COLUMNS, out / "clean" / "platform_bills.csv")
    _write_csv(base["payments"], PAYMENT_COLUMNS, out / "clean" / "order_payments.csv")
    _write_csv(clean_refunds, REFUND_COLUMNS, out / "clean" / "refunds.csv")
    _write_csv(bills, BILL_COLUMNS, out / "dirty" / "platform_bills.csv")
    _write_csv(dirty_payments, PAYMENT_COLUMNS, out / "dirty" / "order_payments.csv")
    _write_csv(dirty_refunds, REFUND_COLUMNS, out / "dirty" / "refunds.csv")
    write_gt(gt, out / "dirty" / "ground_truth.csv")

    return _verify(out, counts, natural)


def _verify(out: Path, counts: dict, natural: set[str]) -> dict:
    gt = read_gt(out / "dirty" / "ground_truth.csv")
    clean_bills = _read_csv(out / "clean" / "platform_bills.csv")
    dirty_bills = _read_csv(out / "dirty" / "platform_bills.csv")
    clean_refunds = _read_csv(out / "clean" / "refunds.csv")
    dirty_refunds = _read_csv(out / "dirty" / "refunds.csv")
    clean_payments = _read_csv(out / "clean" / "order_payments.csv")
    dirty_payments = _read_csv(out / "dirty" / "order_payments.csv")

    problems = []
    if len(gt) != sum(counts.values()):
        problems.append(f"gt 行数 {len(gt)} ≠ 配置总数 {sum(counts.values())}")
    expected_bills = (len(clean_bills) - counts["drop_bill"] + counts["orphan"]
                      + counts["status_rebill"] + counts["duplicate"]
                      + counts["version_diff"])
    if len(dirty_bills) != expected_bills:
        problems.append(f"脏账单 {len(dirty_bills)} ≠ 守恒式 {expected_bills}")
    if len(dirty_refunds) != len(clean_refunds) - counts["refund_missing"]:
        problems.append("脏退款行数不守恒")
    dropped_payments = {p["order_id"] for p in clean_payments} - \
                       {p["order_id"] for p in dirty_payments}
    if len(dropped_payments) != counts["drop_payment"]:
        problems.append("删支付订单数不守恒")
    gt_orders = {r["order_id"] for r in gt}
    if gt_orders & natural:
        problems.append("自然差异单被埋雷（隔离规则被破坏）")
    if problems:
        raise RuntimeError("自校验失败：" + "；".join(problems))

    per_type = Counter(r["diff_type"] for r in gt)
    return {"clean_bills": len(clean_bills), "dirty_bills": len(dirty_bills),
            "clean_refunds": len(clean_refunds), "dirty_refunds": len(dirty_refunds),
            "clean_payments": len(clean_payments),
            "dirty_payments": len(dirty_payments), "gt_total": len(gt),
            "per_type": dict(per_type)}
