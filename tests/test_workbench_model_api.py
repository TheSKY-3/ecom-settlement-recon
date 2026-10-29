"""模型配置接口：页面输入 key（只存内存）、掩码、验证、清除与回落。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.agent import llm
from src.workbench.app import app

KEY = "sk-page-1234567890abcd"


@pytest.fixture(autouse=True)
def clean_key(monkeypatch):
    llm.set_api_key(None)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    yield
    llm.set_api_key(None)


def test_status_without_key_reports_unavailable():
    body = TestClient(app).get("/api/model").json()
    assert body["provider"] == "deepseek"
    assert body["available"] is False
    assert body["source"] is None
    assert body["key_hint"] is None
    assert body["model"]


def test_save_key_returns_mask_only_and_enables_chat(monkeypatch):
    monkeypatch.setattr(llm, "probe", lambda key: None)
    client = TestClient(app)
    res = client.post("/api/model", json={"api_key": KEY})
    assert res.status_code == 200
    body = res.json()
    assert body["available"] is True
    assert body["source"] == "override"
    assert body["key_hint"] == "sk-…abcd"
    assert KEY not in res.text
    assert client.get("/api/chat/status").json()["available"] is True


def test_invalid_key_is_rejected_and_not_stored(monkeypatch):
    def boom(key):
        raise llm.LLMError("DeepSeek API HTTP 401：invalid key")
    monkeypatch.setattr(llm, "probe", boom)
    client = TestClient(app)
    res = client.post("/api/model", json={"api_key": KEY})
    assert res.status_code == 400
    assert "401" in res.json()["detail"]
    assert KEY not in res.text
    assert client.get("/api/model").json()["available"] is False


def test_short_key_is_rejected_without_network(monkeypatch):
    def boom(key):
        raise AssertionError("不该联网验证太短的 key")
    monkeypatch.setattr(llm, "probe", boom)
    res = TestClient(app).post("/api/model", json={"api_key": "sk-1"})
    assert res.status_code == 400


def test_clear_falls_back_to_env(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env-000000000000")
    monkeypatch.setattr(llm, "probe", lambda key: None)
    client = TestClient(app)
    assert client.get("/api/model").json()["source"] == "env"
    posted = client.post("/api/model", json={"api_key": KEY}).json()
    assert posted["source"] == "override"
    cleared = client.delete("/api/model").json()
    assert cleared["available"] is True
    assert cleared["source"] == "env"
    assert cleared["key_hint"] == "sk-…0000"


def test_runtime_key_used_for_calls_and_never_leaked(monkeypatch):
    captured = {}

    class FakeResp:
        def __enter__(self): return self
        def __exit__(self, *exc): return False
        def read(self):
            return b'{"choices":[{"message":{"content":"ok"}}]}'

    def fake_urlopen(req, timeout=None):
        captured["auth"] = req.headers.get("Authorization")
        return FakeResp()

    monkeypatch.setattr(llm, "_urlopen", fake_urlopen)
    llm.set_api_key(KEY)
    assert llm.chat([{"role": "user", "content": "hi"}]) == "ok"
    assert captured["auth"] == f"Bearer {KEY}"
    llm.set_api_key(None)
    with pytest.raises(llm.LLMError) as exc:
        llm.chat([{"role": "user", "content": "hi"}])
    assert KEY not in str(exc.value)
