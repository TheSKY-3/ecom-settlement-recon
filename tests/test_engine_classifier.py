import pytest

from src.engine.classifier import classify
from src.engine.matcher import load_world


@pytest.fixture()
def findings(engine_env):
    synth, db = engine_env
    return classify(load_world(synth, db))


def _one(findings, oid):
    got = [f for f in findings if f["order_id"] == oid]
    assert len(got) == 1, f"{oid} 应恰有一条发现，实际 {got}"
    return got[0]


def test_nine_variants_detected(findings):
    assert _one(findings, "abcdef0123456789abcdef0123456789")["variant"] == "孤儿账单"
    assert _one(findings, "o2")["variant"] == "删账单"
    # o3 同时被开账单（状态不一致）又没退款（退款遗漏）——两类发现并存，判分按类型各算各的
    assert {f["variant"] for f in findings if f["order_id"] == "o3"} == {
        "取消单被开账单", "退款缺失"}
    assert _one(findings, "o6")["variant"] == "退款缺失"
    assert _one(findings, "o7")["variant"] == "整单重复"
    assert _one(findings, "o8")["variant"] == "两版并存"
    assert _one(findings, "o9")["variant"] == "费率错误"
    assert _one(findings, "o10")["variant"] == "漏运费"
    assert _one(findings, "o5")["variant"] == "支付与单据不符"
    assert _one(findings, "o11")["variant"] == "不该有的退款"


def test_unapproved_canceled_paid_has_no_finding(findings):
    assert [f for f in findings if f["order_id"] == "o4"] == []


def test_clean_order_no_finding(findings):
    assert [f for f in findings if f["order_id"] == "o1"] == []


def test_confidence_and_shape(findings):
    f = _one(findings, "o9")
    assert f["confidence"] == 1.0 and f["target_side"] == "bills"
    assert f["evidence"]["rate"] == "0.10"
    assert set(f) == {"finding_id", "order_id", "diff_type", "variant",
                      "target_side", "confidence", "description", "evidence",
                      "amount", "verified"}
    assert [x["finding_id"] for x in findings] == [
        f"F{i:06d}" for i in range(1, len(findings) + 1)]


def test_amount_per_variant(findings):
    """涉案金额按发现现场复算，各分支口径与考卷注入金额一致（判分器逐条对账）。"""
    def amt(oid):
        return _one(findings, oid)["amount"]
    assert amt("abcdef0123456789abcdef0123456789") == 90.00   # 孤儿账单：账单结算额
    assert amt("o2") == 90.00    # 删账单：规则卡期望结算额（货款100+运费10-佣金20）
    assert amt("o6") == 110.00   # 退款缺失：涉案 = 已付金额
    assert amt("o7") == 90.00    # 整单重复：多结算的那一笔
    assert amt("o8") == 5.00     # 版本差异：两版结算额差（95.00 vs 90.00）
    assert amt("o9") == 10.00    # 费率错误：佣金 20→10
    assert amt("o10") == 10.00   # 漏运费：运费 10→0
    assert amt("o11") == 110.00  # 不该有的退款：退款额
    assert amt("o12") == 110.00  # 删支付：支付侧口径 = 货款100+运费10（非结算额）
    o3 = {f["variant"]: f["amount"] for f in findings if f["order_id"] == "o3"}
    assert o3 == {"取消单被开账单": 90.00, "退款缺失": 110.00}
    f5 = _one(findings, "o5")    # 支付与单据不符（自然差异）：|99.00-110.00|
    assert f5["variant"] == "支付与单据不符" and f5["amount"] == 11.00
    # 金额均为非负、两位小数
    assert all(x["amount"] is None or (x["amount"] >= 0 and
              round(x["amount"], 2) == x["amount"]) for x in findings)


def test_diff_types_within_whitelist(findings):
    assert {f["diff_type"] for f in findings} <= {
        "单边账", "金额不符", "状态不一致", "退款遗漏", "重复结算", "版本差异"}
