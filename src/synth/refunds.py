"""干净世界规则 R3：取消/不可达且支付已审批的订单，全额退款。

真实 Olist 数据里没有退款流水表，这本账是全量合成的；
"退款遗漏"雷 = 干净退款表里删行（见 injectors.inject_refund_missing）。
"""

from datetime import datetime, timedelta

from src.synth.config import NO_BILL_STATUSES, REFUND_OFFSET_DAYS

REFUND_COLUMNS = ["refund_id", "order_id", "refund_amount", "refund_date", "refund_reason"]


def _shift(date_str: str, days: int) -> str:
    d = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
    return (d + timedelta(days=days)).isoformat()


def generate_refunds(orders: list[dict], pay_sum_by_order: dict[str, float]) -> list[dict]:
    refunds = []
    for order in orders:
        if order["order_status"] not in NO_BILL_STATUSES:
            continue
        approved = order.get("order_approved_at") or ""
        if not approved:
            continue
        total = pay_sum_by_order.get(order["order_id"])
        if total is None:
            continue
        refunds.append({
            "refund_id": f"R_{order['order_id']}",
            "order_id": order["order_id"],
            "refund_amount": f"{round(total, 2):.2f}",
            "refund_date": _shift(approved, REFUND_OFFSET_DAYS),
            "refund_reason": order["order_status"],
        })
    return refunds
