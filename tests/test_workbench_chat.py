"""工作台多轮对话端点测试：状态、降级、历史、重置、预算与模型替身。"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from src.agent import chat, llm
from src.workbench import export as export_mod
from src.workbench.app import _CHAT, app
from tests.test_workbench_data import env  # noqa: F401  数据夹具

FINDINGS = [
    {"finding_id": "F000001", "order_id": "o2", "diff_type": "单边账", "variant": "删账单",
     "target_side": "bills", "confidence": 1.0, "description": "账单缺失", "verified": True},
    {"finding_id": "F000002", "order_id": "o3", "diff_type": "金额不符", "variant": "费率错误",
     "target_side": "bills", "confidence": 1.0, "description": "佣金费率错误", "verified": True},
]
SCORE = {"gt_total": 4, "finding_total": 2, "tp": 2, "fn": 0, "fp": 0,
         "fp_natural": 0, "fp_other": 0, "recall": 1.0, "precision_other": 1.0}


@pytest.fixture()
def client(env, tmp_path, monkeypatch):  # noqa: F811
    out = tmp_path / "engine"
    out.mkdir()
    (out / "findings.json").write_text(
        json.dumps({"audit": {}, "findings": FINDINGS}), encoding="utf-8")
    (out / "score.json").write_text(json.dumps(SCORE), encoding="utf-8")
    monkeypatch.setenv("RECON_ENGINE_DIR", str(out))
    monkeypatch.setenv("RECON_AGENT_DIR", str(tmp_path / "agent"))
    monkeypatch.setenv("RECON_EXPORT_DIR", str(tmp_path / "exports"))
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    _CHAT.clear()
    _CHAT.engine = chat.ChatEngine()
    export_mod.cleanup()
    try:
        yield TestClient(app)
    finally:
        _CHAT.clear()
        _CHAT.engine = chat.ChatEngine()
        export_mod.cleanup()


def _submit(answer: str, refs: list[str] | None = None) -> dict:
    return {"content": "", "tool_calls": [{
        "id": "submit", "name": "submit_chat_answer",
        "arguments": json.dumps({"answer": answer, "refs": refs or []},
                                ensure_ascii=False),
    }]}


def test_chat_status_without_key(client):
    body = client.get("/api/chat/status").json()
    assert body["available"] is False
    assert body["max_turns"] == 20 and body["max_message_chars"] == 1000
    assert body["model"] == "deepseek-flash"


def test_chat_fallback_no_key(client):
    r = client.post("/api/chat", json={"message": "一共发现多少条？"})
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "fallback" and body["reason"] == "NO_KEY"
    assert body["session_id"] and body["session_turns"] == 1
    assert "2" in body["answer"]
    assert body["status"] == "ready"


def test_chat_no_key_answers_data_inventory(client):
    """没配模型也要能通过对话查表清单：走确定性本地回答，不靠模型。"""
    body = client.post(
        "/api/chat", json={"message": "这批评测涉及几张表，各有多少行？"}).json()
    assert body["source"] == "fallback"
    assert body["reason"] == "NO_KEY"
    assert "8 份表" in body["answer"]
    assert "输入 3 份" in body["answer"]


def test_chat_no_key_export_still_returns_file(client):
    """没配模型也能导出：本地识别导出意图，后端确定性生成并给下载卡片。"""
    body = client.post(
        "/api/chat", json={"message": "把单边账导成 Excel 对照表。"}).json()
    assert body["source"] == "fallback"
    assert len(body["artifacts"]) == 1
    art = body["artifacts"][0]
    # both 口径：GT 的 o1 单边账 + 与引擎 o2 配对的 1 行 → 2 行、2 个订单
    assert art["rows"] == 2 and art["orders"] == 2
    assert art["sheets"][0]["name"] == "对照明细"
    assert client.get(art["url"]).status_code == 200


def test_chat_history_and_reset(client):
    first = client.post("/api/chat", json={"message": "一共发现多少条？"}).json()
    sid = first["session_id"]
    hist = client.get(f"/api/chat/{sid}")
    assert hist.status_code == 200
    body = hist.json()
    assert [m["role"] for m in body["messages"]] == ["user", "assistant"]
    assert body["messages"][1]["content"] == first["answer"]
    assert body["max_turns"] == 20

    assert client.delete(f"/api/chat/{sid}").json()["reset"] is True
    assert client.get(f"/api/chat/{sid}").status_code == 404
    assert client.delete(f"/api/chat/{sid}").status_code == 404


def test_chat_unknown_session_and_empty_message(client):
    r = client.post("/api/chat", json={"message": "hi", "session_id": "nope"})
    assert r.status_code == 404
    assert client.post("/api/chat", json={"message": "   "}).status_code == 400
    assert client.post("/api/chat", json={"message": "x" * 1001}).status_code == 422


def test_chat_validation_failure_falls_back(client, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setattr(llm, "available", lambda: True)
    _CHAT.engine = chat.ChatEngine(
        gateway=lambda messages, tools: _submit("金额 999.99 元。"))
    body = client.post("/api/chat", json={"message": "一共发现多少条？"}).json()
    assert body["source"] == "fallback"
    assert body["reason"] == "VALIDATION_FAILED"
    assert body["model_calls"] == 1
    assert "999.99" not in body["answer"]
    assert "2" in body["answer"]


def test_chat_llm_tool_loop(client, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setattr(llm, "available", lambda: True)
    scripted = [
        {"content": "", "tool_calls": [{"id": "c1", "name": "get_overview",
                                        "arguments": "{}"}]},
        _submit("这批共 4 条差异。"),
    ]
    _CHAT.engine = chat.ChatEngine(gateway=lambda messages, tools: scripted.pop(0))
    body = client.post("/api/chat", json={"message": "这批有多少差异？"}).json()
    assert body["source"] == "llm"
    assert body["answer"] == "这批共 4 条差异。"
    assert body["session_turns"] == 1
    assert body["tool_trace"][0].startswith("查询概览")
    hist = client.get(f"/api/chat/{body['session_id']}").json()
    assert hist["messages"][-1]["source"] == "llm"


def test_chat_tool_steps_and_activity_endpoint(client, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setattr(llm, "available", lambda: True)
    scripted = [
        {"content": "", "tool_calls": [{"id": "c1", "name": "get_overview",
                                        "arguments": "{}"}]},
        _submit("这批共 4 条差异。"),
    ]
    _CHAT.engine = chat.ChatEngine(gateway=lambda messages, tools: scripted.pop(0))
    body = client.post("/api/chat",
                       json={"message": "这批有多少差异？",
                             "activity_id": "act-api-1"}).json()
    assert body["source"] == "llm"
    assert [s["label"] for s in body["tool_steps"]] == ["读取批次概览", "提交回答"]
    assert body["tool_steps"][0]["status"] == "ok"
    assert body["model_calls"] == 2

    act = client.get("/api/chat/activity/act-api-1")
    assert act.status_code == 200
    data = act.json()
    assert data["done"] is True
    assert [s["label"] for s in data["steps"]] == ["读取批次概览", "提交回答"]
    assert client.get("/api/chat/activity/nope").status_code == 404

    hist = client.get(f"/api/chat/{body['session_id']}").json()
    last = hist["messages"][-1]
    assert last["tool_steps"][0]["label"] == "读取批次概览"
    assert last["model_calls"] == 2 and last["session_turns"] == 1


def test_chat_export_gives_artifact_and_suggestions(client, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setattr(llm, "available", lambda: True)
    scripted = [
        {"content": "", "tool_calls": [{
            "id": "c1", "name": "export_diffs",
            "arguments": json.dumps({"source": "both", "diff_type": "单边账"},
                                    ensure_ascii=False)}]},
        _submit("已生成 Excel 对照表，共 2 行。"),
    ]
    _CHAT.engine = chat.ChatEngine(gateway=lambda messages, tools: scripted.pop(0))
    body = client.post("/api/chat", json={"message": "把单边账导成 Excel。"}).json()
    assert body["source"] == "llm"
    assert len(body["artifacts"]) == 1
    artifact = body["artifacts"][0]
    assert artifact["rows"] == 2 and artifact["url"].startswith("/api/exports/")
    assert artifact["format"] == "xlsx"
    assert body["suggestions"] and body["suggestions"][0]["text"]
    assert client.get(artifact["url"]).status_code == 200

    hist = client.get(f"/api/chat/{body['session_id']}").json()
    assert hist["messages"][-1]["artifacts"][0]["url"] == artifact["url"]
    assert hist["messages"][-1]["suggestions"] == body["suggestions"]


def test_chat_export_keeps_artifact_in_fallback(client, monkeypatch):
    """文件已生成、但模型答错被校验打回时，产物仍应可下载（降级不吞结果）。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setattr(llm, "available", lambda: True)
    scripted = [
        {"content": "", "tool_calls": [{
            "id": "c1", "name": "export_diffs",
            "arguments": json.dumps({"source": "gt"})}]},
        _submit("导出了 999.99 行。"),
    ]
    _CHAT.engine = chat.ChatEngine(gateway=lambda messages, tools: scripted.pop(0))
    body = client.post("/api/chat", json={"message": "导出全部标准答案。"}).json()
    assert body["source"] == "fallback"
    assert body["reason"] == "VALIDATION_FAILED"
    assert len(body["artifacts"]) == 1 and body["artifacts"][0]["rows"] == 4


def test_inventory_facts_expose_counts(client):
    """表数量必须是事实里的字面值，模型才能引用而不被数字校验打回。"""
    result, _ = _CHAT.engine.tools.execute("get_data_inventory")
    assert result["counts"] == {"table_count": 8, "input_count": 3,
                               "reference_count": 3, "gt_count": 4,
                               "finding_count": 2}


def test_strip_export_links_removes_url_and_token():
    """下载链接/token 只放在文件卡片里，正文与引用保持干净。"""
    draft = chat.ChatAnswerDraft(
        answer="已生成 2 行。下载链接：/api/exports/abcdef0123456789",
        refs=["GT000001", "abcdef0123456789"])
    out = chat._strip_export_links(draft, [{"kind": "export",
                                            "token": "abcdef0123456789"}])
    assert "/api/exports" not in out.answer
    assert "下载链接" not in out.answer
    assert out.refs == ["GT000001"]


def test_followup_ordinal_fallback_uses_last_ref(client):
    """多轮里“第一条”指上一轮的例子；模型失败时也要能确定性回答。"""
    engine = _CHAT.engine
    session = chat._Session("t")
    session.last_refs = ["F000001", "o2"]
    local = engine._local_answer(session, "第一条的订单号是什么？", [])
    assert local is not None
    answer, extra = local
    assert "F000001" in answer and "o2" in answer
    assert extra and extra[0]["kind"] == "finding"
