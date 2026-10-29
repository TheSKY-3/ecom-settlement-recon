"""D014 工具增强的离线测试：按类型统计、过滤参数、轮次预算、评测运行器。"""
from __future__ import annotations

import json

import pytest

from src.agent import chat, llm
from tests.test_workbench_data import env  # noqa: F401  数据夹具

FINDINGS = [
    {"finding_id": "F000001", "order_id": "o2", "diff_type": "单边账", "variant": "删账单",
     "target_side": "bills", "confidence": 1.0, "description": "账单缺失", "verified": True},
    {"finding_id": "F000002", "order_id": "o3", "diff_type": "金额不符", "variant": "费率错误",
     "target_side": "bills", "confidence": 1.0, "description": "佣金费率错误", "verified": True},
    # o9 不在 GT 里：模拟自然差异（订单本身金额就不一致，不是引擎判错）
    {"finding_id": "F000003", "order_id": "o9", "diff_type": "金额不符", "variant": "自然差异",
     "target_side": "refunds", "confidence": 0.9, "description": "金额不一致", "verified": True},
    {"finding_id": "F000004", "order_id": "o2", "diff_type": "金额不符", "variant": "费率错误",
     "target_side": "payments", "confidence": 0.9, "description": "佣金费率错误", "verified": False},
]
SCORE = {"gt_total": 4, "finding_total": 4, "tp": 2, "fn": 2, "fp": 2,
         "fp_natural": 1, "fp_other": 1, "recall": 0.5, "precision_other": 0.6667,
         "fp_natural_ids": ["o9"]}


@pytest.fixture()
def rich_env(env, tmp_path, monkeypatch):  # noqa: F811
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
        "id": "submit", "name": "submit_chat_answer",
        "arguments": json.dumps({"answer": answer, "refs": refs or []},
                                ensure_ascii=False)}]}


def _tool(name: str) -> dict:
    return {"content": "", "tool_calls": [{
        "id": f"call-{name}", "name": name,
        "arguments": json.dumps({}, ensure_ascii=False)}]}


def _tools(*names: str) -> dict:
    return {"content": "", "tool_calls": [
        {"id": f"call-{i}-{n}", "name": n,
         "arguments": json.dumps({}, ensure_ascii=False)}
        for i, n in enumerate(names, start=1)]}


def _stats(env):  # noqa: F811
    return chat.ChatTools().execute("get_type_stats", {})[0]


def _by_type(out: dict, diff_type: str) -> dict:
    return next(i for i in out["by_type"] if i["diff_type"] == diff_type)


def test_type_stats_aggregates_by_type(rich_env):
    out = _stats(rich_env)
    single = _by_type(out, "单边账")
    assert (single["gt"], single["findings"], single["tp"], single["fn"], single["fp"]) == \
        (2, 1, 1, 1, 0)
    assert single["recall"] == 0.5 and single["precision"] == 1.0

    amount = _by_type(out, "金额不符")
    assert (amount["gt"], amount["findings"], amount["tp"], amount["fp"]) == (1, 3, 1, 2)
    assert amount["fp_natural"] == 1 and amount["fp_other"] == 1
    assert amount["precision"] == 0.3333          # 含自然差异
    assert amount["precision_other"] == 0.5       # 剔除自然差异

    refund = _by_type(out, "退款遗漏")
    assert refund["findings"] == 0 and refund["fn"] == 1
    assert refund["precision"] is None            # 没报过，不给假数字

    assert out["totals"] == {"gt": 4, "findings": 4, "tp": 2, "fn": 2, "fp": 2,
                             "fp_natural": 1, "fp_other": 1, "recall": 0.5,
                             "precision": 0.5, "precision_other": 0.6667}
    assert out["by_side"]["findings"] == {"bills": 2, "payments": 1, "refunds": 1}


def test_type_stats_never_echoes_natural_ids(rich_env):
    text = json.dumps(_stats(rich_env), ensure_ascii=False)
    assert "fp_natural_ids" not in text
    assert "o9" not in text


def test_search_engine_confidence_filter(rich_env):
    tools = chat.ChatTools()
    high, trace = tools.execute("search_diffs",
                                {"source": "engine", "min_confidence": 0.95})
    assert high["total"] == 2
    low, _ = tools.execute("search_diffs", {"source": "engine",
                                            "min_confidence": 0.9,
                                            "max_confidence": 0.9})
    assert low["total"] == 2
    assert "置信度≥0.95" in trace


def test_search_engine_verified_and_natural_only(rich_env):
    tools = chat.ChatTools()
    unverified, _ = tools.execute("search_diffs",
                                  {"source": "engine", "verified": False})
    assert [r["finding_id"] for r in unverified["rows"]] == ["F000004"]
    natural, _ = tools.execute("search_diffs",
                               {"source": "engine", "natural_only": True})
    assert natural["total"] == 1
    assert natural["rows"][0]["order_id"] == "o9"
    assert natural["rows"][0]["confidence"] == 0.9


def test_search_gt_rejects_engine_only_filters(rich_env):
    out, trace = chat.ChatTools().execute(
        "search_diffs", {"source": "gt", "natural_only": True})
    assert out["error"] == "INVALID_ARGS"
    assert "engine" in out["message"] and "不匹配" in trace
    ok, _ = chat.ChatTools().execute("search_diffs", {"source": "gt"})
    assert ok["total"] == 4


def test_type_stats_is_advertised_and_budget_raised():
    assert "get_type_stats" in chat.TOOL_NAMES
    assert chat._TOOL_LABELS["get_type_stats"] == "按类型统计"
    assert chat.MAX_TOOL_ROUNDS == 6
    schemas = {t["function"]["name"] for t in chat.TOOL_SCHEMAS}
    assert schemas == {"get_overview", "search_diffs", "get_type_stats",
                       "get_diff", "get_order", "get_engine_score",
                       "get_data_inventory", "export_diffs"}


def test_six_tool_rounds_then_submit(rich_env, monkeypatch):
    monkeypatch.setattr(llm, "available", lambda: True)
    scripted = [_tool("get_engine_score")] * 6 + [_submit("召回 100.0%。")]
    service = chat.ChatService(engine=chat.ChatEngine(
        gateway=lambda messages, tools: scripted.pop(0)))
    out = service.turn(None, "连续查六次再回答。")
    assert out.source == "llm"
    assert out.model_calls == 7
    assert [s["kind"] for s in out.tool_steps] == ["tool"] * 6 + ["submit"]


def test_seventh_tool_round_falls_back(rich_env, monkeypatch):
    monkeypatch.setattr(llm, "available", lambda: True)
    scripted = [_tool("get_engine_score")] * 7 + [_submit("召回 100.0%。")]
    service = chat.ChatService(engine=chat.ChatEngine(
        gateway=lambda messages, tools: scripted.pop(0)))
    out = service.turn(None, "第七次还不收手。")
    assert out.source == "fallback"
    assert out.reason == "ROUNDS_EXCEEDED"


def test_parallel_tool_calls_in_one_round_are_all_executed(rich_env, monkeypatch):
    # 实测 deepseek-flash 会一轮并发多个只读调用（get_diff×2、search_diffs×4）；
    # 旧逻辑"每轮必须恰好一个"会把这些正确答案判成 MODEL_OUTPUT_INVALID 降级。
    monkeypatch.setattr(llm, "available", lambda: True)
    scripted = [_tools("get_engine_score", "get_overview"),
                _submit("召回 100.0%。")]
    service = chat.ChatService(engine=chat.ChatEngine(
        gateway=lambda messages, tools: scripted.pop(0)))
    out = service.turn(None, "同时看整体分数和概览。")
    assert out.source == "llm"
    assert out.model_calls == 2
    assert [s["name"] for s in out.tool_steps
            if s["kind"] == "tool"] == ["get_engine_score", "get_overview"]
    kinds = [f.get("kind") for f in out.facts]
    assert "engine" in kinds and "overview" in kinds


def test_submit_mixed_with_tools_is_rejected(rich_env, monkeypatch):
    monkeypatch.setattr(llm, "available", lambda: True)
    mixed = {"content": "", "tool_calls": [
        {"id": "c1", "name": "get_overview", "arguments": "{}"},
        {"id": "c2", "name": "submit_chat_answer",
         "arguments": json.dumps({"answer": "共 4 条。", "refs": []},
                                 ensure_ascii=False)}]}
    service = chat.ChatService(engine=chat.ChatEngine(
        gateway=lambda messages, tools: mixed))
    out = service.turn(None, "概况？")
    assert out.source == "fallback"
    assert out.reason == "MODEL_OUTPUT_INVALID"


def test_too_many_parallel_calls_are_rejected(rich_env, monkeypatch):
    monkeypatch.setattr(llm, "available", lambda: True)
    many = _tools(*(["get_engine_score"] * (chat.MAX_CALLS_PER_ROUND + 1)))
    service = chat.ChatService(engine=chat.ChatEngine(
        gateway=lambda messages, tools: many))
    out = service.turn(None, "一次发五个。")
    assert out.reason == "MODEL_OUTPUT_INVALID"


def test_parallel_calls_still_bounded_by_total_tool_budget(rich_env, monkeypatch):
    monkeypatch.setattr(llm, "available", lambda: True)
    rounds = (chat.MAX_TOOL_CALLS // chat.MAX_CALLS_PER_ROUND) + 1
    scripted = [_tools(*(["get_engine_score"] * chat.MAX_CALLS_PER_ROUND))] * rounds
    service = chat.ChatService(engine=chat.ChatEngine(
        gateway=lambda messages, tools: scripted.pop(0)))
    out = service.turn(None, "每轮四个，一直查。")
    assert out.source == "fallback"
    assert out.reason == "ROUNDS_EXCEEDED"
    assert chat.MAX_TOOL_CALLS == 12


def test_offline_eval_runner_counts_pass_and_fail(rich_env):
    from evals import tool_use

    cases = [
        {"id": "pass", "steps": [("get_overview", {})],
         "check": lambda f, ex: (True, "ok")},
        {"id": "fail", "steps": [("get_overview", {})],
         "check": lambda f, ex: (False, "故意失败")},
        {"id": "boom", "steps": [("get_overview", {})],
         "check": lambda f, ex: 1 / 0},
    ]
    result = tool_use.run_offline(cases=cases)
    assert result["total"] == 3 and result["passed"] == 1
    assert result["coverage"] == 0.3333
    assert result["failed_ids"] == ["fail", "boom"]
    assert "ZeroDivisionError" in result["items"][2]["detail"]


def test_search_echoes_engine_filters_as_fact(rich_env):
    from src.agent import guardrails

    out, _ = chat.ChatTools().execute(
        "search_diffs", {"source": "engine", "min_confidence": 0.95})
    assert out["filters"] == {"min_confidence": 0.95}
    # 回显之后，模型复述"0.95 以上"才是可核实的事实；此前会被判不可追溯而整轮降级
    assert guardrails.check("置信度 0.95 以上共 2 条。", [out])["ok"] is True
    assert guardrails.check("置信度 0.95 以上共 2 条。",
                            [{"kind": "diffs", "total": 2}])["ok"] is False


def test_overview_carries_order_id_len(rich_env):
    from src.agent import guardrails

    ov = chat.build_overview_facts()
    assert ov["order_id_len"] == 32
    assert guardrails.check("请提供完整 32 位订单号。", [ov])["ok"] is True
    assert guardrails.check("请提供完整 32 位订单号。", [{"kind": "x"}])["ok"] is False


def test_live_eval_aggregates_without_touching_network(rich_env, monkeypatch):
    from evals import tool_use

    monkeypatch.setattr(llm, "available", lambda: True)
    fake_service = type("Fake", (), {"turn": lambda self, sid, q: chat.ChatTurnResult(
        session_id="s1", source="llm", answer="这批共 4 条差异。",
        tool_steps=[{"kind": "tool", "name": "get_overview"}],
        model_calls=2)})()

    result = tool_use.run_live(
        cases=[{"id": "one", "question": "这批有多少差异？",
                "steps": [("get_overview", {})], "check": lambda f, ex: (True, "ok")}],
        service_factory=lambda: fake_service)
    assert result["first_hit_rate"] == 1.0
    assert result["coverage_rate"] == 1.0
    assert result["facts_rate"] == 1.0
    assert result["llm_rate"] == 1.0
    assert result["avg_rounds"] == 2.0
    assert result["failed_ids"] == []
    assert result["items"][0]["used"] == ["get_overview"]
