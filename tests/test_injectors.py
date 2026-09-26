import random

import pytest

from src.synth import config
from src.synth.bills import generate_bills
from src.synth.refunds import generate_refunds
from src.synth.injectors import (allocate_pools, inject_amount_mismatch,
                                 inject_duplicate, inject_refund_missing,
                                 inject_single_sided,
                                 inject_status_inconsistency,
                                 inject_version_diff)

COUNTS = {"drop_bill": 2, "orphan": 1, "drop_payment": 1, "wrong_rate": 1,
          "missing_freight": 1, "status_rebill": 1, "refund_missing": 1,
          "duplicate": 1, "version_diff": 1}
ACTIVE = [f"o{i}" for i in range(1, 9)]


@pytest.fixture()
def world():
    orders, items_by_order, payments = [], {}, []
    for oid in ACTIVE:
        orders.append({"order_id": oid, "order_status": "delivered",
                       "order_purchase_timestamp": "2017-10-02 10:00:00",
                       "order_approved_at": "2017-10-03 10:00:00"})
        items_by_order[oid] = [{"seller_id": "s1", "price": "100.00",
                                "freight_value": "10.00"}]
        payments.append({"order_id": oid, "payment_sequential": "1",
                         "payment_type": "credit_card", "payment_installments": "1",
                         "payment_value": "110.00"})
    for oid, status in (("c1", "canceled"), ("c2", "unavailable")):
        orders.append({"order_id": oid, "order_status": status,
                       "order_purchase_timestamp": "2017-10-02 10:00:00",
                       "order_approved_at": "2017-10-03 10:00:00"})
        items_by_order[oid] = [{"seller_id": "s1", "price": "100.00",
                                "freight_value": "10.00"}]
        payments.append({"order_id": oid, "payment_sequential": "1",
                         "payment_type": "credit_card", "payment_installments": "1",
                         "payment_value": "110.00"})
    orders_index = {o["order_id"]: o for o in orders}
    bills = generate_bills(orders, items_by_order)
    refunds = generate_refunds(orders, {"c1": 110.0, "c2": 110.0})
    return orders_index, items_by_order, bills, payments, refunds


def run_all(world, seed=config.SEED, counts=COUNTS):
    orders_index, items_by_order, bills, payments, refunds = world
    pools = allocate_pools(random.Random(seed), list(ACTIVE), ["c1", "c2"],
                           ["c1", "c2"], orders_index, counts)
    gt = []
    inject_single_sided(bills, payments, orders_index, pools, gt)
    inject_amount_mismatch(bills, pools, gt)
    inject_status_inconsistency(bills, orders_index, items_by_order, pools, gt)
    inject_refund_missing(refunds, pools, gt)
    inject_duplicate(bills, pools, gt)
    inject_version_diff(bills, pools, gt)
    return pools, bills, payments, refunds, gt


def test_allocate_pools_counts_and_disjoint(world):
    orders_index = world[0]
    pools = allocate_pools(random.Random(config.SEED), list(ACTIVE), ["c1", "c2"],
                           ["c1", "c2"], orders_index, COUNTS)
    for key, n in COUNTS.items():
        assert len(pools[key]) == n, key
    active_pools = ["drop_bill", "drop_payment", "wrong_rate", "missing_freight",
                    "duplicate", "version_diff"]
    ids = [oid for k in active_pools for oid in pools[k]]
    assert len(ids) == len(set(ids)), "活跃单池必须互斥"
    assert set(pools["status_rebill"]) <= {"c1", "c2"}
    assert set(pools["refund_missing"]) <= {"c1", "c2"}


def test_orphan_ids_are_new_32hex(world):
    orders_index = world[0]
    counts = dict(COUNTS, status_rebill=0, refund_missing=0)
    pools = allocate_pools(random.Random(config.SEED), list(ACTIVE), [], [],
                           orders_index, counts)
    for oid in pools["orphan"]:
        assert len(oid) == 32
        assert all(c in "0123456789abcdef" for c in oid)
        assert oid not in orders_index


def test_full_injection_gt_count_and_ids(world):
    _, _, _, _, gt = run_all(world)
    assert len(gt) == 10
    assert [r["gt_id"] for r in gt] == [f"GT{i:06d}" for i in range(1, 11)]


def test_each_variant_verifiable(world):
    pools, bills, payments, refunds, gt = run_all(world)

    def bill_of(oid):
        return [b for b in bills if b["order_id"] == oid]

    for oid in pools["drop_bill"]:
        assert bill_of(oid) == []
    for oid in pools["orphan"]:
        b = bill_of(oid)[0]
        assert (b["price_amount"], b["freight_amount"], b["commission_fee"],
                b["settlement_amount"]) == ("100.00", "10.00", "20.00", "90.00")
    for oid in pools["drop_payment"]:
        assert all(p["order_id"] != oid for p in payments)
    for oid in pools["wrong_rate"]:
        b = bill_of(oid)[0]
        assert b["commission_rate"] == "0.10"
        assert b["commission_fee"] == "10.00"
        assert b["settlement_amount"] == "100.00"
    for oid in pools["missing_freight"]:
        b = bill_of(oid)[0]
        assert b["freight_amount"] == "0.00"
        assert b["settlement_amount"] == "80.00"
    for oid in pools["status_rebill"]:
        b = bill_of(oid)[0]
        assert b["commission_rate"] == "0.20"
        assert b["settlement_amount"] == "90.00"
        assert b["issued_date"] == "2017-10-10"
    for oid in pools["refund_missing"]:
        assert all(r["order_id"] != oid for r in refunds)
    for oid in pools["duplicate"]:
        rows = bill_of(oid)
        assert len(rows) == 2
        assert {rows[0]["bill_id"], rows[1]["bill_id"]} == \
            {f"B_{oid}_1", f"B_{oid}_1_DUP"}
    for oid in pools["version_diff"]:
        rows = bill_of(oid)
        assert len(rows) == 2
        by_ver = {r["version"]: r for r in rows}
        assert by_ver["1"]["commission_rate"] == "0.15"
        assert by_ver["1"]["commission_fee"] == "15.00"
        assert by_ver["1"]["settlement_amount"] == "95.00"
        assert by_ver["2"]["commission_rate"] == "0.20"
        assert by_ver["2"]["commission_fee"] == "20.00"
        assert by_ver["2"]["settlement_amount"] == "90.00"
        assert by_ver["2"]["issued_date"] == "2017-10-11"


def test_determinism_same_seed(world):
    a = run_all(world)
    b = run_all(world)
    assert a == b
