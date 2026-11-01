"""六类雷的注入器：往干净三本账里埋已知错误，同时追加标准答案行。

纪律：
- 池子互斥由 allocate_pools 保证（一个订单最多中一种雷）；
- 注入器只改 bills / payments / refunds 三本账的**副本语义上的行**，不动订单和明细；
- 每个 gt 行都必须能从脏数据里验证（tests/test_injectors.py 逐类断言）。
"""

import random

from src.synth.bills import amounts_from_items, shift_date
from src.synth.config import (BILL_OFFSET_DAYS, COMMISSION_RATE, NO_BILL_STATUSES,
                              OLD_RATE, WRONG_RATE)
from src.synth.ground_truth import make_row


def allocate_pools(rng: random.Random, active_ids: list[str], rebill_ids: list[str],
                   refund_ids: list[str], orders_index: dict[str, dict],
                   counts: dict[str, int],
                   nonzero_freight_ids: set[str] | None = None) -> dict[str, list[str]]:
    """从候选池不放回抽样，保证六类雷落在互斥的订单集合上。

    nonzero_freight_ids：明细运费合计 > 0 的订单集合。漏运费雷只许落在其中——
    运费本来就是 0 的订单埋"漏运费"等于没埋（雷不可判，P2 全量跑分暴露的缺陷）。
    """
    ids = list(active_ids)
    rng.shuffle(ids)

    def take(n: int) -> list[str]:
        nonlocal ids
        if n > len(ids):
            raise ValueError(f"注入池不足：需要 {n}，只剩 {len(ids)}")
        chunk, ids = ids[:n], ids[n:]
        return chunk

    def take_filtered(n: int, allowed: set[str]) -> list[str]:
        nonlocal ids
        chosen, rest = [], []
        for oid in ids:
            if len(chosen) < n and oid in allowed:
                chosen.append(oid)
            else:
                rest.append(oid)
        ids = rest
        if len(chosen) < n:
            raise ValueError(f"注入池不足：漏运费需要 {n}，零运费过滤后只剩 {len(chosen)}")
        return chosen

    pools = {
        "drop_bill": take(counts["drop_bill"]),
        "drop_payment": take(counts["drop_payment"]),
        "wrong_rate": take(counts["wrong_rate"]),
        "missing_freight": (take_filtered(counts["missing_freight"],
                                          set(nonzero_freight_ids))
                            if nonzero_freight_ids is not None
                            else take(counts["missing_freight"])),
        "duplicate": take(counts["duplicate"]),
        "version_diff": take(counts["version_diff"]),
    }
    rebills = list(rebill_ids)
    rng.shuffle(rebills)
    if counts["status_rebill"] > len(rebills):
        raise ValueError("状态不一致池不足")
    pools["status_rebill"] = rebills[:counts["status_rebill"]]
    refs = list(refund_ids)
    rng.shuffle(refs)
    if counts["refund_missing"] > len(refs):
        raise ValueError("退款遗漏池不足")
    pools["refund_missing"] = refs[:counts["refund_missing"]]
    orphans = []
    while len(orphans) < counts["orphan"]:
        oid = "".join(rng.choices("0123456789abcdef", k=32))
        if oid not in orders_index and oid not in orphans:
            orphans.append(oid)
    pools["orphan"] = orphans
    return pools


def _bill_of(bills: list[dict], oid: str) -> dict:
    return next(row for row in bills if row["order_id"] == oid)


def _recompute(row: dict, rate: float) -> None:
    """按行内货款/运费与给定费率重算 佣金/应付 三列。"""
    price = float(row["price_amount"])
    freight = float(row["freight_amount"])
    fee = round(rate * price, 2)
    row["commission_rate"] = f"{rate:.2f}"
    row["commission_fee"] = f"{fee:.2f}"
    row["settlement_amount"] = f"{price + freight - fee:.2f}"


def inject_single_sided(bills: list[dict], payments: list[dict],
                        orders_index: dict[str, dict], pools: dict,
                        gt_rows: list[dict]) -> None:
    drop = set(pools["drop_bill"])
    dropped_amount = {}
    for b in bills:
        if b["order_id"] in drop:
            dropped_amount[b["order_id"]] = (dropped_amount.get(b["order_id"], 0.0)
                                             + float(b["settlement_amount"]))
    bills[:] = [b for b in bills if b["order_id"] not in drop]
    for oid in sorted(pools["drop_bill"]):
        gt_rows.append(make_row(oid, "单边账", "删账单", "bills",
                                "账单缺失：有明细有支付但无账单", len(gt_rows) + 1,
                                amount=dropped_amount[oid]))
    for oid in pools["orphan"]:
        bills.append({"bill_id": f"B_{oid}_1", "order_id": oid, "seller_id": "SYNTH",
                      "version": "1", "issued_date": "2023-01-01",
                      "commission_rate": "0.20", "commission_fee": "20.00",
                      "freight_amount": "10.00", "price_amount": "100.00",
                      "settlement_amount": "90.00"})
        gt_rows.append(make_row(oid, "单边账", "孤儿账单", "bills",
                                "孤儿账单：订单不存在", len(gt_rows) + 1, amount=90.00))
    drop_pay = set(pools["drop_payment"])
    dropped_paid = {}
    for p in payments:
        if p["order_id"] in drop_pay:
            dropped_paid[p["order_id"]] = (dropped_paid.get(p["order_id"], 0.0)
                                           + float(p["payment_value"]))
    payments[:] = [p for p in payments if p["order_id"] not in drop_pay]
    for oid in sorted(pools["drop_payment"]):
        gt_rows.append(make_row(oid, "单边账", "删支付", "payments",
                                "支付缺失", len(gt_rows) + 1,
                                amount=dropped_paid[oid]))


def inject_amount_mismatch(bills: list[dict], pools: dict, gt_rows: list[dict]) -> None:
    for oid in pools["wrong_rate"]:
        row = _bill_of(bills, oid)
        before = float(row["settlement_amount"])
        _recompute(row, WRONG_RATE)
        gt_rows.append(make_row(oid, "金额不符", "费率错误", "bills",
                                f"佣金费率错误：{WRONG_RATE:.2f} ≠ 标准费率",
                                len(gt_rows) + 1,
                                amount=abs(float(row["settlement_amount"]) - before)))
    for oid in pools["missing_freight"]:
        row = _bill_of(bills, oid)
        if float(row["freight_amount"]) == 0:
            raise ValueError(f"漏运费雷不可埋：{oid} 本身运费为 0（雷将无法判定）")
        before = float(row["settlement_amount"])
        row["freight_amount"] = "0.00"
        _recompute(row, float(row["commission_rate"]))
        gt_rows.append(make_row(oid, "金额不符", "漏运费", "bills",
                                "账单漏加运费", len(gt_rows) + 1,
                                amount=abs(float(row["settlement_amount"]) - before)))


def inject_status_inconsistency(bills: list[dict], orders_index: dict[str, dict],
                                items_by_order: dict[str, list[dict]], pools: dict,
                                gt_rows: list[dict]) -> None:
    for oid in pools["status_rebill"]:
        order = orders_index[oid]
        assert order["order_status"] in NO_BILL_STATUSES
        price, freight, fee = amounts_from_items(items_by_order[oid])
        issued = shift_date(order.get("order_approved_at")
                            or order["order_purchase_timestamp"], BILL_OFFSET_DAYS)
        bills.append({"bill_id": f"B_{oid}_1", "order_id": oid,
                      "seller_id": items_by_order[oid][0]["seller_id"], "version": "1",
                      "issued_date": issued, "commission_rate": f"{COMMISSION_RATE:.2f}",
                      "commission_fee": f"{fee:.2f}", "freight_amount": f"{freight:.2f}",
                      "price_amount": f"{price:.2f}",
                      "settlement_amount": f"{price + freight - fee:.2f}"})
        gt_rows.append(make_row(oid, "状态不一致", "取消单被开账单", "bills",
                                "取消/不可达订单出现在账单中", len(gt_rows) + 1,
                                amount=price + freight - fee))


def inject_refund_missing(refunds: list[dict], pools: dict, gt_rows: list[dict]) -> None:
    drop = set(pools["refund_missing"])
    dropped_amount = {}
    for r in refunds:
        if r["order_id"] in drop:
            dropped_amount[r["order_id"]] = (dropped_amount.get(r["order_id"], 0.0)
                                             + float(r["refund_amount"]))
    refunds[:] = [r for r in refunds if r["order_id"] not in drop]
    for oid in sorted(drop):
        gt_rows.append(make_row(oid, "退款遗漏", "退款缺失", "refunds",
                                "已付款的取消单无退款记录", len(gt_rows) + 1,
                                amount=dropped_amount[oid]))


def inject_duplicate(bills: list[dict], pools: dict, gt_rows: list[dict]) -> None:
    for oid in pools["duplicate"]:
        row = _bill_of(bills, oid)
        dup = dict(row)
        dup["bill_id"] = row["bill_id"] + "_DUP"
        bills.append(dup)
        gt_rows.append(make_row(oid, "重复结算", "整单重复", "bills",
                                "同订单同版本账单重复", len(gt_rows) + 1,
                                amount=float(row["settlement_amount"])))


def inject_version_diff(bills: list[dict], pools: dict, gt_rows: list[dict]) -> None:
    for oid in pools["version_diff"]:
        row = _bill_of(bills, oid)
        v1 = dict(row)
        _recompute(v1, OLD_RATE)
        v1["bill_id"] = f"B_{oid}_1"
        v1["version"] = "1"
        row["bill_id"] = f"B_{oid}_2"
        row["version"] = "2"
        row["issued_date"] = shift_date(row["issued_date"], 1)
        _recompute(row, COMMISSION_RATE)
        bills.append(v1)
        gt_rows.append(make_row(oid, "版本差异", "两版并存", "bills",
                                "两版账单并存，按 v2 对账", len(gt_rows) + 1,
                                amount=abs(float(row["settlement_amount"])
                                           - float(v1["settlement_amount"]))))
