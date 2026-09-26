"""干净世界规则 R1/R2/R4：平台账单只开给"未取消且有明细"的订单。

应付卖家 = 货款 + 运费 − 佣金（佣金 = 费率 × 货款）。
日期回退链：审批日 +7 天 →（缺审批）下单日 +7 天。
"""

from datetime import datetime, timedelta

from src.synth.config import BILL_OFFSET_DAYS, COMMISSION_RATE, NO_BILL_STATUSES

BILL_COLUMNS = ["bill_id", "order_id", "seller_id", "version", "issued_date",
                "commission_rate", "commission_fee", "freight_amount",
                "price_amount", "settlement_amount"]


def _shift(date_str: str, days: int) -> str | None:
    if not date_str:
        return None
    d = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
    return (d + timedelta(days=days)).isoformat()


def generate_bills(orders: list[dict], items_by_order: dict[str, list[dict]],
                   rate: float = COMMISSION_RATE) -> list[dict]:
    bills = []
    for order in orders:
        oid = order["order_id"]
        if order["order_status"] in NO_BILL_STATUSES:
            continue
        items = items_by_order.get(oid)
        if not items:
            continue
        price = round(sum(float(i["price"]) for i in items), 2)
        freight = round(sum(float(i["freight_value"]) for i in items), 2)
        fee = round(rate * price, 2)
        issued = (_shift(order.get("order_approved_at") or "", BILL_OFFSET_DAYS)
                  or _shift(order["order_purchase_timestamp"], BILL_OFFSET_DAYS))
        bills.append({
            "bill_id": f"B_{oid}_1",
            "order_id": oid,
            "seller_id": items[0]["seller_id"],
            "version": "1",
            "issued_date": issued,
            "commission_rate": f"{rate:.2f}",
            "commission_fee": f"{fee:.2f}",
            "freight_amount": f"{freight:.2f}",
            "price_amount": f"{price:.2f}",
            "settlement_amount": f"{price + freight - fee:.2f}",
        })
    return bills
