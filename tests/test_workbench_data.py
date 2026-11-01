import csv
import json
import sqlite3

import pytest

from src.workbench import data as wbdata

GT_COLUMNS = ["gt_id", "order_id", "diff_type", "variant", "target_side",
              "description", "amount"]


def _write_csv(path, columns, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        w.writerows(rows)


def _rewrite_gt_with_amounts(synth, amounts: dict[str, str]) -> None:
    """给 env 夹具的 GT 补 amount 列（考卷 v1.2 形态），其余行原样保留。"""
    gt_path = synth / "dirty" / "ground_truth.csv"
    rows = list(csv.DictReader(open(gt_path, encoding="utf-8")))
    for r in rows:
        r["amount"] = amounts[r["gt_id"]]
    _write_csv(gt_path, GT_COLUMNS, rows)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    synth = tmp_path / "synthetic"
    bills = [{"bill_id": "B_1", "order_id": "o1", "seller_id": "s1", "version": "1",
              "issued_date": "2026-01-01", "commission_rate": "0.20", "commission_fee": "2.00",
              "freight_amount": "5.00", "price_amount": "10.00", "settlement_amount": "13.00"}]
    pays = [{"order_id": "o1", "payment_sequential": "1", "payment_type": "credit_card",
             "payment_installments": "1", "payment_value": "15.00"}]
    refs = [{"refund_id": "R_o3", "order_id": "o3", "refund_amount": "7.00",
             "refund_date": "2026-02-01"}]
    gt = [
        {"gt_id": "GT000001", "order_id": "o1", "diff_type": "单边账", "variant": "删账单",
         "target_side": "bills", "description": "账单缺失：有明细有支付但无账单"},
        {"gt_id": "GT000002", "order_id": "o2", "diff_type": "金额不符", "variant": "费率错",
         "target_side": "bills", "description": "佣金按 0.10 计算，应为 0.20"},
        {"gt_id": "GT000003", "order_id": "o3", "diff_type": "退款遗漏", "variant": "该退未退",
         "target_side": "refunds", "description": "取消单已付款但无退款记录"},
        {"gt_id": "GT000004", "order_id": "o2", "diff_type": "单边账", "variant": "删账单",
         "target_side": "bills", "description": "账单缺失：有明细有支付但无账单"},
    ]
    _write_csv(synth / "clean" / "platform_bills.csv", list(bills[0]), bills)
    _write_csv(synth / "clean" / "refunds.csv", list(refs[0]), refs)
    _write_csv(synth / "clean" / "order_payments.csv", list(pays[0]), pays)
    # 脏世界：o1 的雷是"删账单"，所以脏账单里不能有 o1——放一张无关订单的正常账单
    dirty_bills = [dict(bills[0], bill_id="B_9", order_id="o9")]
    _write_csv(synth / "dirty" / "platform_bills.csv", list(dirty_bills[0]), dirty_bills)
    _write_csv(synth / "dirty" / "refunds.csv", list(refs[0]), refs)
    _write_csv(synth / "dirty" / "order_payments.csv", list(pays[0]), pays)
    _write_csv(synth / "dirty" / "ground_truth.csv", GT_COLUMNS, gt)

    db = tmp_path / "olist.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        "CREATE TABLE orders (order_id TEXT, customer_id TEXT, order_status TEXT,"
        " order_purchase_timestamp TEXT);"
        "CREATE TABLE order_items (order_id TEXT, order_item_id INTEGER, product_id TEXT,"
        " seller_id TEXT, price REAL, freight_value REAL);"
        "CREATE INDEX idx_o ON orders(order_id);"
        "CREATE INDEX idx_i ON order_items(order_id);"
        "INSERT INTO orders VALUES ('o1','c1','delivered','2026-01-01 10:00:00');"
        "INSERT INTO order_items VALUES ('o1',1,'p1','s1',10.0,5.0);"
    )
    conn.commit()
    conn.close()

    monkeypatch.setenv("RECON_SYNTHETIC_DIR", str(synth))
    monkeypatch.setenv("RECON_DB_PATH", str(db))
    return synth


def test_overview_counts(env):
    ov = wbdata.load_overview()
    assert ov["clean"] == {"bills": 1, "refunds": 1, "payments": 1}
    assert ov["dirty"]["bills"] == 1
    assert ov["gt"]["total"] == 4
    assert ov["gt"]["by_type"] == {"单边账": 2, "金额不符": 1, "退款遗漏": 1}
    assert ov["gt"]["by_side"] == {"bills": 3, "refunds": 1}


def test_diffs_filter_and_pagination(env):
    page1 = wbdata.load_diffs(None, None, None, 1, 2)
    assert page1["total"] == 4 and page1["page"] == 1 and len(page1["rows"]) == 2
    page2 = wbdata.load_diffs(None, None, None, 2, 2)
    assert len(page2["rows"]) == 2 and page2["rows"][0]["gt_id"] == "GT000003"
    only_single = wbdata.load_diffs("单边账", None, None, 1, 50)
    assert only_single["total"] == 2
    assert all(r["diff_type"] == "单边账" for r in only_single["rows"])
    search = wbdata.load_diffs(None, None, "o2", 1, 50)
    assert {r["gt_id"] for r in search["rows"]} == {"GT000002", "GT000004"}
    side = wbdata.load_diffs(None, "refunds", None, 1, 50)
    assert [r["gt_id"] for r in side["rows"]] == ["GT000003"]


def test_ledger_assembles_five_sources(env):
    led = wbdata.load_ledger("GT000001")
    assert led is not None
    assert led["gt"]["order_id"] == "o1"
    assert led["bills"] == []          # o1 的雷是"删账单"，脏账单里无此单
    assert len(led["payments"]) == 1 and led["payments"][0]["payment_value"] == "15.00"
    assert led["orders"][0]["order_status"] == "delivered"
    assert led["items"][0]["price"] == 10.0
    assert led["refunds"] == []
    assert wbdata.load_ledger("GT999999") is None


def test_missing_data_dir_gives_clear_error(monkeypatch, tmp_path):
    monkeypatch.setenv("RECON_SYNTHETIC_DIR", str(tmp_path / "nowhere"))
    with pytest.raises(FileNotFoundError) as e:
        wbdata.load_overview()
    assert "scripts/build_synthetic.py" in str(e.value)


def test_overview_money_and_engine_money_degradation(env, tmp_path, monkeypatch):
    """考卷 v1.2：概览带涉案金额汇总；引擎结果未生成时 engine_money 优雅降级。"""
    monkeypatch.setenv("RECON_ENGINE_DIR", str(tmp_path / "no_engine"))
    _rewrite_gt_with_amounts(env, {"GT000001": "13.00", "GT000002": "1.00",
                                   "GT000003": "7.00", "GT000004": "2.50"})
    ov = wbdata.load_overview()
    assert ov["gt"]["total_amount"] == 23.50
    assert ov["gt"]["by_type_amount"] == {"单边账": 15.50, "金额不符": 1.00,
                                          "退款遗漏": 7.00}
    assert ov["engine_money"] is None


def test_overview_engine_money_from_findings(env, tmp_path, monkeypatch):
    _rewrite_gt_with_amounts(env, {"GT000001": "13.00", "GT000002": "1.00",
                                   "GT000003": "7.00", "GT000004": "2.50"})
    engine = tmp_path / "engine"
    engine.mkdir()
    findings = [{"order_id": "o9", "diff_type": "金额不符", "amount": 11.0},
                {"order_id": "o2", "diff_type": "单边账", "amount": 90.0}]
    (engine / "findings.json").write_text(
        json.dumps({"audit": {}, "findings": findings}), encoding="utf-8")
    monkeypatch.setenv("RECON_ENGINE_DIR", str(engine))
    ov = wbdata.load_overview()
    assert ov["engine_money"] == {"total_amount": 101.0,
                                  "by_type_amount": {"金额不符": 11.0, "单边账": 90.0}}


def test_diffs_sort_by_amount(env):
    _rewrite_gt_with_amounts(env, {"GT000001": "13.00", "GT000002": "1.00",
                                   "GT000003": "7.00", "GT000004": "2.50"})
    page = wbdata.load_diffs(None, None, None, 1, 50, sort="amount_desc")
    assert [r["gt_id"] for r in page["rows"]] == [
        "GT000001", "GT000003", "GT000004", "GT000002"]
    with pytest.raises(ValueError):
        wbdata.load_diffs(None, None, None, 1, 50, sort="bogus")
