"""引擎测试公共夹具：11 个订单的小世界，覆盖九种变体 + 自然差异 + 未审批取消单。"""
import csv
import sqlite3

import pytest

GT_COLUMNS = ["gt_id", "order_id", "diff_type", "variant", "target_side", "description"]
BILL_COLUMNS = ["bill_id", "order_id", "seller_id", "version", "issued_date",
                "commission_rate", "commission_fee", "freight_amount",
                "price_amount", "settlement_amount"]
PAY_COLUMNS = ["order_id", "payment_sequential", "payment_type",
               "payment_installments", "payment_value"]
REF_COLUMNS = ["refund_id", "order_id", "refund_amount", "refund_date"]
ORPHAN = "abcdef0123456789abcdef0123456789"


def bill(oid, *, version="1", rate="0.20", price="100.00", freight="10.00",
         fee="20.00", settle="90.00", suffix=""):
    return {"bill_id": f"B_{oid}_1{suffix}", "order_id": oid, "seller_id": "s1",
            "version": version, "issued_date": "2026-01-08", "commission_rate": rate,
            "commission_fee": fee, "freight_amount": freight,
            "price_amount": price, "settlement_amount": settle}


def _write(path, columns, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        w.writerows(rows)


@pytest.fixture()
def engine_env(tmp_path, monkeypatch):
    """o1 活跃正常；o2 删账单；o3 取消已审批被开账单；o4 取消未审批有支付（应无发现）；
    o5 自然差异（支付≠明细）；o6 取消已审批退款缺失；o7 重复结算；o8 版本差异；
    o9 费率错误；o10 漏运费；o11 活跃但有退款（不该有的退款）。另加孤儿账单 ORPHAN。"""
    synth = tmp_path / "synthetic"
    orders = [(f"o{i}", status, approved, "2026-01-01 09:00:00")
              for i, (status, approved) in enumerate([
                  ("delivered", "2026-01-01 10:00:00"), ("delivered", "2026-01-02 10:00:00"),
                  ("canceled", "2026-01-03 10:00:00"), ("canceled", ""),
                  ("delivered", "2026-01-05 10:00:00"), ("unavailable", "2026-01-06 10:00:00"),
                  ("delivered", "2026-01-07 10:00:00"), ("delivered", "2026-01-08 10:00:00"),
                  ("delivered", "2026-01-09 10:00:00"), ("delivered", "2026-01-10 10:00:00"),
                  ("delivered", "2026-01-11 10:00:00")], start=1)]
    items = [(f"o{i}", 1, "p1", "s1", 100.0, 10.0) for i in range(1, 12)]

    pays = []
    for i in range(1, 12):
        value = "110.00" if i != 5 else "99.00"   # o5 少付 → 自然差异
        pays.append({"order_id": f"o{i}", "payment_sequential": "1",
                     "payment_type": "credit_card", "payment_installments": "1",
                     "payment_value": value})

    bills = [bill(f"o{i}") for i in (1, 3, 5, 7, 11)]           # o2/o6 无账单；o8/o9/o10 单独给
    bills.append(bill("o7", suffix="_DUP"))                                     # 重复结算
    bills.append(bill("o8", rate="0.15", fee="15.00", settle="95.00"))          # v1 旧费率
    bills.append(dict(bill("o8"), bill_id="B_o8_2", version="2"))               # v2 正确
    bills.append(bill("o9", rate="0.10", fee="10.00", settle="100.00"))         # 费率错误
    bills.append(bill("o10", freight="0.00", fee="20.00", settle="80.00"))      # 漏运费
    bills.append(bill(ORPHAN))                                                  # 孤儿账单

    refunds = [{"refund_id": "R_o1", "order_id": "o1", "refund_amount": "110.00",
                "refund_date": "2026-02-01"}]   # 活跃单有退款 → 不该有的退款
    # o6 取消已审批有支付，但无退款 → 退款遗漏

    _write(synth / "dirty" / "platform_bills.csv", BILL_COLUMNS, bills)
    _write(synth / "dirty" / "order_payments.csv", PAY_COLUMNS, pays)
    _write(synth / "dirty" / "refunds.csv", REF_COLUMNS, refunds)
    _write(synth / "clean" / "platform_bills.csv", BILL_COLUMNS, bills[:1])
    _write(synth / "clean" / "refunds.csv", REF_COLUMNS, refunds)
    _write(synth / "clean" / "order_payments.csv", PAY_COLUMNS, pays)
    _write(synth / "dirty" / "ground_truth.csv", GT_COLUMNS, [])   # 引擎单测不依赖 gt

    db = tmp_path / "olist.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        "CREATE TABLE orders (order_id TEXT, order_status TEXT, order_approved_at TEXT,"
        " order_purchase_timestamp TEXT);"
        "CREATE TABLE order_items (order_id TEXT, order_item_id INTEGER, product_id TEXT,"
        " seller_id TEXT, price REAL, freight_value REAL);"
        "CREATE TABLE order_payments (order_id TEXT, payment_sequential INTEGER,"
        " payment_type TEXT, payment_installments INTEGER, payment_value REAL);"
        "CREATE INDEX idx_o ON orders(order_id);"
        "CREATE INDEX idx_i ON order_items(order_id);")
    conn.executemany("INSERT INTO orders VALUES (?,?,?,?)", orders)
    conn.executemany("INSERT INTO order_items VALUES (?,?,?,?,?,?)", items)
    conn.executemany("INSERT INTO order_payments VALUES (?,?,?,?,?)",
                     [(p["order_id"], 1, "credit_card", 1, float(p["payment_value"]))
                      for p in pays])
    conn.commit()
    conn.close()

    monkeypatch.setenv("RECON_SYNTHETIC_DIR", str(synth))
    monkeypatch.setenv("RECON_DB_PATH", str(db))
    return synth, db
