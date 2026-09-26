"""P3 Agent 测试：全部离线（模型用注入替身，永不碰网络）。"""
from __future__ import annotations

import io
import json
import urllib.error

import pytest

from src.agent import guardrails, llm, tools

ORPHAN = "abcdef0123456789abcdef0123456789"


# ── llm：密钥来自环境变量，错误归一，请求体字段 ────────────────
def test_llm_unavailable_without_key(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    assert llm.available() is False


def test_llm_available_with_key(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    assert llm.available() is True


def test_chat_raises_without_key(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(llm.LLMError):
        llm.chat([{"role": "user", "content": "hi"}])


def test_chat_http_error_normalized(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")

    def fake_urlopen(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {},
                                     io.BytesIO(b'{"error":"bad key"}'))

    monkeypatch.setattr(llm, "_urlopen", fake_urlopen)
    with pytest.raises(llm.LLMError, match="401"):
        llm.chat([{"role": "user", "content": "hi"}])


def test_chat_returns_content_and_sends_config(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["body"] = json.loads(req.data.decode("utf-8"))
        captured["auth"] = req.get_header("Authorization")
        return io.BytesIO(json.dumps(
            {"choices": [{"message": {"content": "答案"}}]}).encode("utf-8"))

    monkeypatch.setattr(llm, "_urlopen", fake_urlopen)
    out = llm.chat([{"role": "user", "content": "hi"}], max_tokens=99)
    assert out == "答案"
    assert captured["auth"].startswith("Bearer ") and "sk-test" in captured["auth"]
    assert captured["body"]["model"] == llm.DEFAULT_MODEL
    assert captured["body"]["effort"] == llm.DEFAULT_EFFORT
    assert captured["body"]["max_tokens"] == 99


# ── guardrails：数字/编号白名单 ────────────────────────────────
def test_check_passes_numbers_and_ids_from_facts():
    oid = "a" * 32
    facts = {"bills": [{"settlement_amount": "145.26", "order_id": oid}],
             "order": [{"order_purchase_timestamp": "2017-10-18 12:14:29"}]}
    out = guardrails.check(f"结算额 145.26，订单 {oid}，下单于 2017-10-18。", facts)
    assert out["ok"], out


def test_check_flags_hallucinated_number():
    facts = {"bills": [{"settlement_amount": "145.26"}]}
    out = guardrails.check("金额是 999.99 元。", facts)
    assert not out["ok"] and "999.99" in out["bad_numbers"]


def test_check_flags_unknown_order_id():
    facts = {"order": [{"order_id": "a" * 32}]}
    out = guardrails.check(f"订单 {'b' * 32} 有问题。", facts)
    assert not out["ok"] and "b" * 32 in out["bad_ids"]


def test_check_allows_percent_variant():
    facts = {"score": {"recall": 1.0}}
    out = guardrails.check("召回率 100%。", facts)
    assert out["ok"], out


def test_check_allows_thousands_separator():
    facts = {"score": {"tp": 1750}}
    out = guardrails.check("共命中 1,750 条。", facts)
    assert out["ok"], out


# ── tools：只读事实收集（复用 engine_env 小世界）───────────────
@pytest.fixture()
def world(engine_env, tmp_path, monkeypatch):
    synth, db = engine_env
    monkeypatch.setenv("RECON_ENGINE_DIR", str(tmp_path / "engine"))
    monkeypatch.setenv("RECON_AGENT_DIR", str(tmp_path / "agent"))
    return synth, db


def test_order_facts_o2_missing_bill(world):
    facts = tools.order_facts("o2")
    assert facts["kind"] == "order"
    assert facts["bills"] == [] and len(facts["payments"]) == 1
    assert facts["order"][0]["order_status"] == "delivered"
    assert len(facts["items"]) == 1


def test_order_facts_orphan(world):
    facts = tools.order_facts(ORPHAN)
    assert len(facts["bills"]) == 1
    assert facts["order"] == [] and facts["items"] == []


def test_order_facts_unknown_returns_none(world):
    assert tools.order_facts("nope") is None


def test_finding_reads_engine_output(world, tmp_path):
    findings = {"audit": {}, "findings": [
        {"finding_id": "F000001", "order_id": "o2", "diff_type": "单边账",
         "variant": "删账单", "target_side": "bills", "confidence": 0.9,
         "description": "有支付无账单", "verified": True,
         "evidence": {"hidden": "should be stripped"}}]}
    out = tmp_path / "engine"
    out.mkdir()
    (out / "findings.json").write_text(
        json.dumps(findings, ensure_ascii=False), encoding="utf-8")
    f = tools.finding("F000001")
    assert f["finding"]["variant"] == "删账单"
    assert "evidence" not in f["finding"]
    assert f["bills"] == [] and len(f["payments"]) == 1
    assert tools.finding("F999999") is None


def test_stats_and_samples(world, tmp_path):
    out = tmp_path / "engine"
    out.mkdir()
    findings = {"audit": {}, "findings": [
        {"finding_id": f"F00000{i}", "order_id": f"o{i}", "diff_type": "单边账",
         "variant": "删账单", "target_side": "bills", "confidence": 0.9,
         "description": "d", "verified": True} for i in (2, 3)]
        + [{"finding_id": "F000009", "order_id": "o9", "diff_type": "金额不符",
            "variant": "费率错误", "target_side": "bills", "confidence": 1.0,
            "description": "d", "verified": True}]}
    (out / "findings.json").write_text(
        json.dumps(findings, ensure_ascii=False), encoding="utf-8")
    (out / "score.json").write_text(
        json.dumps({"recall": 1.0, "tp": 3}), encoding="utf-8")

    stats = tools.stats()
    assert stats["score"]["tp"] == 3
    rows = tools.samples_by_type("单边账", limit=1)["rows"]
    assert len(rows) == 1 and rows[0]["order_id"] in ("o2", "o3")
    assert tools.samples_by_type("版本差异")["rows"] == []
