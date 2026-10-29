from src.synth.refunds import REFUND_COLUMNS, generate_refunds


def _order(oid="o1", status="canceled", approved="2017-10-10 10:56:33"):
    return {"order_id": oid, "order_status": status, "order_approved_at": approved}


def test_canceled_approved_gets_full_refund():
    orders = [_order()]
    refunds = generate_refunds(orders, {"o1": 130.504})
    assert len(refunds) == 1
    r = refunds[0]
    assert list(r.keys()) == REFUND_COLUMNS
    assert r["refund_id"] == "R_o1"
    assert r["order_id"] == "o1"
    assert r["refund_amount"] == "130.50"
    assert r["refund_reason"] == "canceled"
    assert r["refund_date"] == "2017-10-24"


def test_canceled_unapproved_no_refund():
    orders = [_order(approved="")]
    assert generate_refunds(orders, {"o1": 100.0}) == []


def test_unavailable_approved_refund_reason():
    orders = [_order(oid="o2", status="unavailable")]
    refunds = generate_refunds(orders, {"o2": 50.0})
    assert refunds[0]["refund_reason"] == "unavailable"
    assert refunds[0]["refund_amount"] == "50.00"


def test_delivered_and_no_payment_get_nothing():
    orders = [_order(oid="o3", status="delivered"), _order(oid="o4")]
    assert generate_refunds(orders, {"o3": 90.0}) == []
