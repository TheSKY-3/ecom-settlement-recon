"""工作台 Agent 端点测试：/api/agent/status、/api/agent/ask、/api/agent/attribute/{ref}。"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from src.workbench.app import app
from tests.test_workbench_data import env  # noqa: F401  数据夹具
from tests.test_workbench_engine import FINDINGS

SCORE = {"gt_total": 2, "finding_total": 2, "tp": 2, "fn": 0, "fp": 0,
         "fp_natural": 0, "fp_other": 0, "recall": 1.0, "precision_other": 1.0}


@pytest.fixture()
def client(env, tmp_path, monkeypatch):
    out = tmp_path / "engine"
    out.mkdir()
    (out / "findings.json").write_text(
        json.dumps({"audit": {}, "findings": FINDINGS}), encoding="utf-8")
    (out / "score.json").write_text(json.dumps(SCORE), encoding="utf-8")
    (tmp_path / "agent").mkdir()
    monkeypatch.setenv("RECON_ENGINE_DIR", str(out))
    monkeypatch.setenv("RECON_AGENT_DIR", str(tmp_path / "agent"))
    return TestClient(app)


def test_agent_status_without_key(client, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    body = client.get("/api/agent/status").json()
    assert body["available"] is False and body["model"]


def test_agent_status_with_key(client, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    body = client.get("/api/agent/status").json()
    assert body["available"] is True and body["model"] == "deepseek-flash"


def test_agent_ask_capability_hint(client, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    body = client.post("/api/agent/ask", json={"question": "今天天气如何？"}).json()
    assert body["source"] == "fallback" and "能查" in body["answer"]


def test_agent_ask_stats_deterministic(client, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    calls = []
    monkeypatch.setattr("src.agent.llm.chat", lambda msgs, max_tokens=2000:
                        calls.append(msgs))
    body = client.post("/api/agent/ask", json={"question": "一共发现多少条？"}).json()
    assert calls == []
    assert body["source"] == "fallback" and "2" in body["answer"]


def test_agent_attribute_unknown_ref(client):
    body = client.get("/api/agent/attribute/F999999").json()
    assert body["source"] == "fallback" and "找不到" in body["answer"]


def test_agent_attribute_llm_path(client, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setattr("src.agent.llm.chat",
                        lambda msgs, max_tokens=2000: "差异 F000001：订单 o2 账单缺失。")
    body = client.get("/api/agent/attribute/F000001").json()
    assert body["source"] == "llm" and "o2" in body["answer"]


def test_agent_attribute_guardrail_fallback(client, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setattr("src.agent.llm.chat",
                        lambda msgs, max_tokens=2000: "金额 999.99 元。")
    body = client.get("/api/agent/attribute/F000001").json()
    assert body["source"] == "fallback" and "999.99" not in body["answer"]
