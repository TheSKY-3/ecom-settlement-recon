"""验证器：对每条发现独立重推判定谓词。独立 = 不读 evidence，只凭类型从原始视图重算；
推得回去才 verified=True。结论落报告前必须过这道关（spec 第 2 节）。"""
from __future__ import annotations

from src.synth.bills import amounts_from_items
from src.synth.config import NO_BILL_STATUSES, TOLERANCE, WRONG_RATE


def _predicate(world, f: dict) -> bool:
    oid = f["order_id"]
    bills = world.bills_by_order.get(oid, [])
    pays = world.payments_by_order.get(oid, [])
    refunds = world.refunds_by_order.get(oid, [])
    order = world.orders.get(oid)
    if f["diff_type"] == "单边账" and f["variant"] == "孤儿账单":
        return order is None and len(bills) > 0
    if order is None:
        return False
    items = world.items_by_order.get(oid, [])
    no_bill_status = order["order_status"] in NO_BILL_STATUSES
    approved = bool((order.get("order_approved_at") or "").strip())
    paid = round(sum(float(p["payment_value"]) for p in pays), 2)

    if f["diff_type"] == "状态不一致":
        return no_bill_status and len(bills) > 0
    if f["diff_type"] == "退款遗漏":
        return no_bill_status and approved and bool(pays) and not refunds
    if f["diff_type"] == "金额不符" and f["variant"] == "不该有的退款":
        return bool(refunds) and not (no_bill_status and approved)
    if f["diff_type"] == "金额不符" and f["variant"] == "退款金额不符":
        return (bool(refunds) and no_bill_status and approved
                and any(abs(float(r["refund_amount"]) - paid) > TOLERANCE for r in refunds))
    if f["diff_type"] == "单边账" and f["variant"] == "删账单":
        return bool(items) and bool(pays) and not bills and not no_bill_status
    if f["diff_type"] == "单边账" and f["variant"] == "账与支付均缺失":
        return bool(items) and not bills and not pays and not no_bill_status
    if f["diff_type"] == "版本差异":
        return len({b["version"] for b in bills}) > 1
    if f["diff_type"] == "重复结算":
        return len(bills) > 1 and len({b["version"] for b in bills}) == 1
    if f["diff_type"] == "单边账" and f["variant"] == "删支付":
        return bool(items) and bool(bills) and not pays and not no_bill_status
    if f["diff_type"] == "金额不符" and len(bills) == 1 and items:
        exp_price, exp_freight, exp_fee = amounts_from_items(items)
        b = bills[0]
        v = f["variant"]
        if v == "货款不符":
            return abs(float(b["price_amount"]) - exp_price) > TOLERANCE
        if v == "费率错误":
            return (b["commission_rate"] == f"{WRONG_RATE:.2f}"
                    and abs(float(b["commission_fee"]) - exp_fee) > TOLERANCE)
        if v == "费率异常":
            return (b["commission_rate"] != f"{WRONG_RATE:.2f}"
                    and abs(float(b["commission_fee"]) - exp_fee) > TOLERANCE)
        if v == "漏运费":
            return float(b["freight_amount"]) == 0 and abs(exp_freight) > TOLERANCE
        if v == "运费不符":
            return (float(b["freight_amount"]) != 0
                    and abs(float(b["freight_amount"]) - exp_freight) > TOLERANCE)
        if v == "结算额不符":
            return abs(float(b["settlement_amount"])
                       - round(exp_price + exp_freight - exp_fee, 2)) > TOLERANCE
        if v == "支付与单据不符":
            bill_clean = (abs(float(b["price_amount"]) - exp_price) <= TOLERANCE
                          and abs(float(b["commission_fee"]) - exp_fee) <= TOLERANCE
                          and abs(float(b["freight_amount"]) - exp_freight) <= TOLERANCE
                          and abs(float(b["settlement_amount"])
                                  - round(exp_price + exp_freight - exp_fee, 2)) <= TOLERANCE)
            return bill_clean and abs(paid - round(exp_price + exp_freight, 2)) > TOLERANCE
    return False


def verify(world, findings: list[dict]) -> None:
    for f in findings:
        f["verified"] = _predicate(world, f)
