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


# ── loop + attribute：五件套行为（注入假模型）──────────────────
@pytest.fixture()
def finding_world(world, tmp_path):
    out = tmp_path / "engine"
    out.mkdir(exist_ok=True)
    findings = {"audit": {}, "findings": [
        {"finding_id": "F000001", "order_id": "o2", "diff_type": "单边账",
         "variant": "删账单", "target_side": "bills", "confidence": 0.9,
         "description": "有支付与明细但平台账单缺失", "verified": True}]}
    (out / "findings.json").write_text(
        json.dumps(findings, ensure_ascii=False), encoding="utf-8")
    return out


GOOD_ANSWER = ("差异 F000001：订单 o2 有支付 110.00 与明细 1 行，但平台账单 0 行，"
               "属单边账/删账单。建议核对账单生成环节。")


def test_attribute_llm_path(world, finding_world, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    calls = []
    monkeypatch.setattr(llm, "chat", lambda msgs, max_tokens=2000:
                        calls.append(msgs) or GOOD_ANSWER)
    from src.agent import attribute
    out = attribute.attribute("F000001")
    assert out["source"] == "llm" and "110.00" in out["answer"]
    assert len(calls) == 1
    assert out["facts_sha256"]


def test_attribute_hallucination_falls_back(world, finding_world, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    calls = []

    def fake_chat(msgs, max_tokens=2000):
        calls.append(msgs)
        return "账单金额 888.88 元，订单 ffffffff11111111ffffffff11111111 缺失。"

    monkeypatch.setattr(llm, "chat", fake_chat)
    from src.agent import attribute
    out = attribute.attribute("F000001")
    assert out["source"] == "fallback"
    assert "888.88" not in out["answer"]
    assert len(calls) == 2          # 初答 + 重试一次 = 预算上限


def test_attribute_fallback_without_key(world, finding_world, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    from src.agent import attribute
    out = attribute.attribute("F000001")
    assert out["source"] == "fallback"
    assert "F000001" in out["answer"] and "o2" in out["answer"]


def test_attribute_unknown_ref(world, finding_world):
    from src.agent import attribute
    out = attribute.attribute("F999999")
    assert out["source"] == "fallback" and "找不到" in out["answer"]


def test_attribute_writes_trace(world, finding_world, tmp_path, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    from src.agent import attribute
    attribute.attribute("F000001")
    trace_file = tmp_path / "agent" / "trace.jsonl"
    lines = trace_file.read_text(encoding="utf-8").strip().splitlines()
    rec = json.loads(lines[-1])
    assert rec["kind"] == "attribute" and rec["source"] == "fallback"
    assert rec["reason"] == "no_key" and rec["ref"] == "F000001"


# ── ask：意图路由（确定性，模板直答不调模型）───────────────────
def test_ask_order_id_routes_to_facts(world, finding_world, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    calls = []
    monkeypatch.setattr(llm, "chat", lambda msgs, max_tokens=2000:
                        calls.append(msgs) or f"订单 {ORPHAN} 是孤儿账单。")
    from src.agent import ask
    out = ask.ask(f"帮我看看订单 {ORPHAN} 怎么回事")
    assert out["source"] == "llm" and len(calls) == 1


def test_ask_stats_uses_template_without_llm(world, finding_world, tmp_path, monkeypatch):
    out_dir = tmp_path / "engine"
    (out_dir / "score.json").write_text(
        json.dumps({"gt_total": 3, "finding_total": 4, "tp": 3, "fn": 0,
                    "fp": 1, "fp_natural": 1, "fp_other": 0, "recall": 1.0,
                    "precision_other": 1.0}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    calls = []
    monkeypatch.setattr(llm, "chat", lambda msgs, max_tokens=2000: calls.append(msgs))
    from src.agent import ask
    out = ask.ask("引擎成绩怎么样，一共发现多少条？")
    assert calls == []                    # 统计是确定性答案，不花模型调用
    assert out["source"] == "fallback" and "3" in out["answer"]


def test_ask_type_name_gives_stats_and_samples(world, finding_world, tmp_path):
    from src.agent import ask
    out = ask.ask("单边账有哪些例子？")
    assert out["source"] == "fallback"
    assert "F000001" in out["answer"]     # 例子来自事实单


def test_ask_unknown_intent_gives_capability_hint(world, finding_world, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    calls = []
    monkeypatch.setattr(llm, "chat", lambda msgs, max_tokens=2000: calls.append(msgs))
    from src.agent import ask
    out = ask.ask("今天天气如何？")
    assert calls == [] and "能查" in out["answer"] or "能力" in out["answer"]
