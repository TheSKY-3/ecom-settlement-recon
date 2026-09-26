from src.synth.bills import BILL_COLUMNS, generate_bills


def _order(oid="o1", status="delivered", approved="2017-10-10 10:56:33",
           purchase="2017-10-02 10:00:00"):
    return {"order_id": oid, "order_status": status,
            "order_purchase_timestamp": purchase, "order_approved_at": approved}


def test_normal_order_amounts_and_columns():
    orders = [_order()]
    items = {"o1": [{"seller_id": "s1", "price": "100.00", "freight_value": "10.00"}]}
    bills = generate_bills(orders, items)
    assert len(bills) == 1
    b = bills[0]
    assert list(b.keys()) == BILL_COLUMNS
    assert b["bill_id"] == "B_o1_1"
    assert b["order_id"] == "o1"
    assert b["seller_id"] == "s1"
    assert b["version"] == "1"
    assert b["price_amount"] == "100.00"
    assert b["freight_amount"] == "10.00"
    assert b["commission_rate"] == "0.20"
    assert b["commission_fee"] == "20.00"
    assert b["settlement_amount"] == "90.00"
    assert b["issued_date"] == "2017-10-17"


def test_multi_items_sum():
    orders = [_order()]
    items = {"o1": [
        {"seller_id": "s1", "price": "50.00", "freight_value": "5.00"},
        {"seller_id": "s2", "price": "50.00", "freight_value": "5.00"},
    ]}
    b = generate_bills(orders, items)[0]
    assert b["price_amount"] == "100.00"
    assert b["freight_amount"] == "10.00"
    assert b["settlement_amount"] == "90.00"
    assert b["seller_id"] == "s1"


def test_canceled_and_unavailable_get_no_bill():
    orders = [_order("o1", "canceled"), _order("o2", "unavailable"), _order("o3")]
    items = {k: [{"seller_id": "s", "price": "10.00", "freight_value": "1.00"}]
             for k in ("o1", "o2", "o3")}
    bills = generate_bills(orders, items)
    assert [b["order_id"] for b in bills] == ["o3"]


def test_order_without_items_skipped():
    orders = [_order("o1"), _order("o2")]
    items = {"o1": [{"seller_id": "s", "price": "10.00", "freight_value": "1.00"}]}
    bills = generate_bills(orders, items)
    assert [b["order_id"] for b in bills] == ["o1"]


def test_missing_approval_falls_back_to_purchase_date():
    orders = [_order(approved="")]
    items = {"o1": [{"seller_id": "s", "price": "10.00", "freight_value": "1.00"}]}
    b = generate_bills(orders, items)[0]
    assert b["issued_date"] == "2017-10-09"
