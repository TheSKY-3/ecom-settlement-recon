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
                      "target_side", "confidence", "description", "evidence", "verified"}
    assert [x["finding_id"] for x in findings] == [
        f"F{i:06d}" for i in range(1, len(findings) + 1)]


def test_diff_types_within_whitelist(findings):
    assert {f["diff_type"] for f in findings} <= {
        "单边账", "金额不符", "状态不一致", "退款遗漏", "重复结算", "版本差异"}
