import sqlite3

from src.synth.build_dataset import build

COUNTS = {"drop_bill": 2, "orphan": 1, "drop_payment": 1, "wrong_rate": 1,
          "missing_freight": 1, "status_rebill": 1, "refund_missing": 1,
          "duplicate": 1, "version_diff": 1}


def _make_db():
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
    CREATE TABLE orders (order_id TEXT, customer_id TEXT, order_status TEXT,
      order_purchase_timestamp TEXT, order_approved_at TEXT,
      order_delivered_carrier_date TEXT, order_delivered_customer_date TEXT,
      order_estimated_delivery_date TEXT);
    CREATE TABLE order_items (order_id TEXT, order_item_id INTEGER, product_id TEXT,
      seller_id TEXT, shipping_limit_date TEXT, price REAL, freight_value REAL);
    CREATE TABLE order_payments (order_id TEXT, payment_sequential INTEGER,
      payment_type TEXT, payment_installments INTEGER, payment_value REAL);
    """)
    for i in range(1, 9):
        oid = f"o{i}"
        conn.execute("INSERT INTO orders VALUES (?,?,?,?,?,?,?,?)",
                     (oid, "c1", "delivered", "2017-10-02 10:00:00",
                      "2017-10-03 10:00:00", None, None, None))
        conn.execute("INSERT INTO order_items VALUES (?,?,?,?,?,?,?)",
                     (oid, 1, "p1", "s1", None, 100.00, 10.00))
        conn.execute("INSERT INTO order_payments VALUES (?,?,?,?,?)",
                     (oid, 1, "credit_card", 1, 110.00))
    for oid, status in (("c1", "canceled"), ("c2", "unavailable")):
        conn.execute("INSERT INTO orders VALUES (?,?,?,?,?,?,?,?)",
                     (oid, "c1", status, "2017-10-02 10:00:00",
                      "2017-10-03 10:00:00", None, None, None))
        conn.execute("INSERT INTO order_items VALUES (?,?,?,?,?,?,?)",
                     (oid, 1, "p1", "s1", None, 100.00, 10.00))
        conn.execute("INSERT INTO order_payments VALUES (?,?,?,?,?)",
                     (oid, 1, "credit_card", 1, 110.00))
    # 自然差异单：支付 90 ≠ 明细 110（禁止被埋雷）
    conn.execute("INSERT INTO orders VALUES (?,?,?,?,?,?,?,?)",
                 ("nm1", "c1", "delivered", "2017-10-02 10:00:00",
                  "2017-10-03 10:00:00", None, None, None))
    conn.execute("INSERT INTO order_items VALUES (?,?,?,?,?,?,?)",
                 ("nm1", 1, "p1", "s1", None, 100.00, 10.00))
    conn.execute("INSERT INTO order_payments VALUES (?,?,?,?,?)",
                 ("nm1", 1, "credit_card", 1, 90.00))
    conn.commit()
    return conn


def test_build_writes_files_and_verifies(tmp_path):
    conn = _make_db()
    summary = build(conn, tmp_path, counts=COUNTS)
    for sub, name in [("clean", "platform_bills.csv"), ("clean", "order_payments.csv"),
                      ("clean", "refunds.csv"), ("dirty", "platform_bills.csv"),
                      ("dirty", "order_payments.csv"), ("dirty", "refunds.csv"),
                      ("dirty", "ground_truth.csv")]:
        assert (tmp_path / sub / name).exists(), f"{sub}/{name}"
    assert summary["gt_total"] == 10
    # 脏账单 = 9 张净账单 − 删2 + 孤儿1 + 重开1 + 重复1 + 新增v1 1
    assert summary["clean_bills"] == 9
    assert summary["dirty_bills"] == 11
    assert summary["dirty_refunds"] == 1  # c1/c2 有退款，删 1 条
    assert summary["per_type"]["单边账"] == 4
    assert summary["per_type"]["金额不符"] == 2


def test_natural_mismatch_order_never_injected(tmp_path):
    conn = _make_db()
    build(conn, tmp_path, counts=COUNTS)
    dirty_bills = (tmp_path / "dirty" / "platform_bills.csv").read_text(encoding="utf-8")
    gt = (tmp_path / "dirty" / "ground_truth.csv").read_text(encoding="utf-8")
    assert "nm1" not in gt
    assert "B_nm1_1" in dirty_bills          # 账单还在
    assert "B_nm1_1_DUP" not in dirty_bills  # 没被重复


def test_build_is_deterministic(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    build(_make_db(), a, counts=COUNTS)
    build(_make_db(), b, counts=COUNTS)
    for sub, name in [("clean", "platform_bills.csv"), ("clean", "refunds.csv"),
                      ("dirty", "platform_bills.csv"), ("dirty", "ground_truth.csv")]:
        assert (a / sub / name).read_text(encoding="utf-8") == \
               (b / sub / name).read_text(encoding="utf-8"), f"{sub}/{name}"
