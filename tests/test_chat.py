"""D013 多轮对话测试：工具、白名单、会话预算、模型循环全部离线。"""
from __future__ import annotations

import io
import json

import pytest

from src.agent import chat, llm
from tests.test_workbench_data import env  # noqa: F401  数据夹具

FINDINGS = [
    {"finding_id": "F000001", "order_id": "o2", "diff_type": "单边账", "variant": "删账单",
     "target_side": "bills", "confidence": 1.0, "description": "账单缺失", "verified": True},
    {"finding_id": "F000002", "order_id": "o3", "diff_type": "金额不符", "variant": "费率错误",
     "target_side": "bills", "confidence": 1.0, "description": "佣金费率错误", "verified": True},
]
SCORE = {"gt_total": 4, "finding_total": 2, "tp": 2, "fn": 0, "fp": 0,
         "fp_natural": 0, "fp_other": 0, "recall": 1.0, "precision_other": 1.0,
         "fp_natural_ids": ["should-not-enter-the-prompt"]}


@pytest.fixture()
def chat_env(env, tmp_path, monkeypatch):  # noqa: F811
    out = tmp_path / "engine"
    out.mkdir()
    (out / "findings.json").write_text(
        json.dumps({"audit": {}, "findings": FINDINGS}), encoding="utf-8")
    (out / "score.json").write_text(json.dumps(SCORE), encoding="utf-8")
    monkeypatch.setenv("RECON_ENGINE_DIR", str(out))
    monkeypatch.setenv("RECON_AGENT_DIR", str(tmp_path / "agent"))
    return env


def _submit(answer: str, refs: list[str] | None = None) -> dict:
    return {"content": "", "tool_calls": [{
        "id": "submit",
        "name": "submit_chat_answer",
        "arguments": json.dumps({"answer": answer, "refs": refs or []},
                                ensure_ascii=False),
    }]}


def _tool(name: str, args: dict | None = None) -> dict:
    return {"content": "", "tool_calls": [{
        "id": f"call-{name}",
        "name": name,
        "arguments": json.dumps(args or {}, ensure_ascii=False),
    }]}


def test_overview_facts_have_counts_shares_and_stripped_engine(chat_env):
    facts = chat.build_overview_facts()
    assert facts["gt"]["total"] == 4
    assert facts["gt"]["by_type"]["单边账"] == 2
    assert facts["gt"]["share_pct"]["单边账"] == "50.0%"
    assert facts["engine"]["finding_total"] == 2
    assert "fp_natural_ids" not in facts["engine"]


def test_search_diffs_is_compact_and_filtered(chat_env):
    out, trace = chat.ChatTools().execute(
        "search_diffs", {"source": "gt", "diff_type": "单边账", "limit": 1})
    assert out["total"] == 2 and len(out["rows"]) == 1
    assert out["rows"][0]["gt_id"] in {"GT000001", "GT000004"}
    assert "单边账" in trace


def test_search_does_not_echo_user_query(chat_env):
    out, _ = chat.ChatTools().execute("search_diffs", {"q": "999.99", "limit": 1})
    assert "999.99" not in json.dumps(out, ensure_ascii=False)


def test_get_diff_and_order_tools(chat_env):
    tools = chat.ChatTools()
    diff, _ = tools.execute("get_diff", {"ref": "GT000001"})
    assert diff["order_id"] == "o1"
    assert diff["bills"] == []
    order, _ = tools.execute("get_order", {"order_id": "o1"})
    assert order["kind"] == "order" and order["order"][0]["order_status"] == "delivered"
    missing, trace = tools.execute("get_order", {"order_id": "nope"})
    assert missing["error"] == "NOT_FOUND" and "未找到" in trace


def test_engine_score_tool_trace_is_useful(chat_env):
    out, trace = chat.ChatTools().execute("get_engine_score", {})
    assert out["score"]["finding_total"] == 2
    assert trace == "召回 100.0% · 发现 2 条"


def test_validate_answer_accepts_grounded_numbers_and_ids():
    oid = "a" * 32
    facts = [{"kind": "order", "order_id": oid, "bills": [{"settlement_amount": "10.00"}]}]
    draft = chat.ChatAnswerDraft(answer=f"订单 {oid} 的结算额是 10.00。", refs=[oid])
    assert chat.validate_chat_answer(draft, facts) == []


def test_validate_answer_rejects_hallucinated_number_and_ref():
    oid = "a" * 32
    facts = [{"kind": "order", "order_id": oid, "bills": [{"settlement_amount": "10.00"}]}]
    draft = chat.ChatAnswerDraft(answer=f"订单 {oid} 的结算额是 999.99。", refs=[oid])
    assert "NUMBER_NOT_TRACEABLE" in chat.validate_chat_answer(draft, facts)

    draft = chat.ChatAnswerDraft(answer="订单不存在。", refs=["GT999999"])
    assert "REF_NOT_TRACEABLE" in chat.validate_chat_answer(draft, facts)


def test_validate_answer_requires_citation_for_ids():
    oid = "a" * 32
    facts = [{"kind": "order", "order_id": oid}]
    draft = chat.ChatAnswerDraft(answer=f"订单 {oid} 有差异。", refs=[])
    assert "ID_NOT_CITED" in chat.validate_chat_answer(draft, facts)


def test_validate_answer_accepts_one_decimal_score_forms():
    facts = [{"kind": "overview", "engine": {"recall": 1.0,
                                             "precision_other": 1.0}}]
    draft = chat.ChatAnswerDraft(answer="召回 1.0，精确率 100.0%。", refs=[])
    assert chat.validate_chat_answer(draft, facts) == []


def test_repair_chat_refs_adds_only_traceable_ids():
    oid = "a" * 32
    facts = [{"kind": "order", "order_id": oid}]
    draft = chat.ChatAnswerDraft(answer=f"订单 {oid} 有差异。", refs=[])
    fixed = chat.repair_chat_refs(draft, facts)
    assert fixed.refs == [oid]
    assert chat.validate_chat_answer(fixed, facts) == []

    unknown = chat.ChatAnswerDraft(answer="GT999999 有差异。", refs=[])
    assert chat.repair_chat_refs(unknown, facts).refs == []
    assert "ID_NOT_CITED" in chat.validate_chat_answer(
        chat.repair_chat_refs(unknown, facts), facts)


def test_llm_chat_with_tools_parses_tool_calls(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return io.BytesIO(json.dumps({
            "choices": [{"message": {"content": None, "tool_calls": [{
                "id": "call-1", "type": "function",
                "function": {"name": "get_overview", "arguments": "{}"},
            }]}}],
        }).encode("utf-8"))

    monkeypatch.setattr(llm, "_urlopen", fake_urlopen)
    out = llm.chat_with_tools(
        [{"role": "user", "content": "hi"}],
        [{"type": "function", "function": {"name": "get_overview", "parameters": {}}}])
    assert out["tool_calls"][0]["name"] == "get_overview"
    assert captured["body"]["tool_choice"] == "auto"
    assert captured["body"]["tools"][0]["function"]["name"] == "get_overview"


def test_chat_service_multi_turn_with_fake_gateway(chat_env, monkeypatch):
    monkeypatch.setattr(llm, "available", lambda: True)
    scripted = [
        _tool("get_overview"),
        _submit("这批共 4 条差异。"),
        _tool("search_diffs", {"source": "gt", "diff_type": "单边账", "limit": 2}),
        _submit("单边账有 2 条，例如 GT000001。", ["GT000001"]),
    ]
    seen = []

    def fake_gateway(messages, tools):
        seen.append(messages)
        assert any(t["function"]["name"] == "submit_chat_answer" for t in tools)
        return scripted.pop(0)

    service = chat.ChatService(engine=chat.ChatEngine(gateway=fake_gateway))
    first = service.turn(None, "这批有多少差异？")
    assert first.source == "llm" and first.answer == "这批共 4 条差异。"
    assert first.tool_trace and first.session_turns == 1

    second = service.turn(first.session_id, "单边账有哪些例子？")
    assert second.session_id == first.session_id
    assert second.source == "llm" and "GT000001" in second.answer
    assert second.session_turns == 2
    hist = service.history(first.session_id)
    assert [m["role"] for m in hist] == ["user", "assistant", "user", "assistant"]
    assert len(seen) == 4


def test_chat_service_accepts_direct_grounded_answer(chat_env, monkeypatch):
    monkeypatch.setattr(llm, "available", lambda: True)
    service = chat.ChatService(engine=chat.ChatEngine(
        gateway=lambda messages, tools: {
            "content": "这批共 4 条差异。", "tool_calls": []}))
    out = service.turn(None, "这批有多少差异？")
    assert out.source == "llm"
    assert out.reason is None
    assert "4" in out.answer


def test_chat_service_validation_failure_falls_back(chat_env, monkeypatch):
    monkeypatch.setattr(llm, "available", lambda: True)
    service = chat.ChatService(engine=chat.ChatEngine(
        gateway=lambda messages, tools: _submit("金额 999.99 元。")))
    out = service.turn(None, "一共发现多少条？")
    assert out.source == "fallback"
    assert out.reason == "VALIDATION_FAILED"
    assert "999.99" not in out.answer
    assert "2" in out.answer


def test_chat_service_no_key_uses_deterministic_fallback(chat_env, monkeypatch):
    monkeypatch.setattr(llm, "available", lambda: False)
    service = chat.ChatService()
    out = service.turn(None, "一共发现多少条？")
    assert out.source == "fallback" and out.reason == "NO_KEY"
    assert "2" in out.answer and out.session_turns == 1


def test_chat_service_turn_limit():
    service = chat.ChatService(max_turns=1)
    service.engine = chat.ChatEngine(gateway=lambda messages, tools: _submit("好的。"))
    # 引擎可用性由测试替身覆盖；这里直接走 no-key 分支会拿不到会话预算，故用假 key。
    import os
    os.environ["DEEPSEEK_API_KEY"] = "sk-test"
    try:
        first = service.turn(None, "第一问")
        second = service.turn(first.session_id, "第二问")
        assert second.status == "unavailable"
        assert second.reason == "SESSION_LIMIT"
    finally:
        os.environ.pop("DEEPSEEK_API_KEY", None)


def test_chat_turn_exposes_structured_tool_steps(chat_env, monkeypatch):
    monkeypatch.setattr(llm, "available", lambda: True)
    scripted = [_tool("get_overview"), _submit("这批共 4 条差异。")]
    service = chat.ChatService(
        engine=chat.ChatEngine(gateway=lambda messages, tools: scripted.pop(0)))
    out = service.turn(None, "这批有多少差异？", activity_id="act-test-1")
    assert out.source == "llm"
    assert len(out.tool_steps) == 2
    first, last = out.tool_steps
    assert first["kind"] == "tool" and first["name"] == "get_overview"
    assert first["label"] == "读取批次概览"
    assert first["status"] == "ok" and first["duration_ms"] >= 0
    assert "批次" in first["detail"]
    assert last["kind"] == "submit" and last["label"] == "提交回答"
    assert "引用" in last["detail"]
    assert out.tool_trace[0].startswith("查询概览")

    activity = service.activity("act-test-1")
    assert activity["done"] is True
    assert [s["label"] for s in activity["steps"]] == ["读取批次概览", "提交回答"]


def test_chat_activity_is_readable_while_turn_runs(chat_env, monkeypatch):
    monkeypatch.setattr(llm, "available", lambda: True)
    scripted = [_tool("get_overview"), _submit("这批共 4 条差异。")]
    seen = {}
    calls = {"n": 0}

    def fake_gateway(messages, tools):
        calls["n"] += 1
        if calls["n"] == 2:
            seen["live"] = service.activity("act-live-1")
        return scripted.pop(0)

    service = chat.ChatService(engine=chat.ChatEngine(gateway=fake_gateway))
    out = service.turn(None, "这批有多少差异？", activity_id="act-live-1")
    assert out.source == "llm"
    assert seen["live"]["done"] is False
    assert seen["live"]["steps"][0]["label"] == "读取批次概览"
    assert seen["live"]["steps"][0]["status"] == "ok"
