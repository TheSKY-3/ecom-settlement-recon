"""工作台 UI 静态契约：对话为默认页、数据源条、合并数据页、导出与产物。"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from src.workbench.app import app

STATIC = Path(__file__).resolve().parents[1] / "src" / "workbench" / "static"


def test_chat_page_markup_is_present():
    html = TestClient(app).get("/").text
    for token in (
        'id="view-chat"', 'id="chat-log"', 'id="chat-form"',
        'id="chat-input"', 'id="chat-send"', 'id="chat-new"',
        'id="chat-notice"', 'id="chat-quick"', 'id="chat-suggest"',
        'id="chat-turns"', 'aria-live="polite"',
        'id="model-btn"', 'id="model-modal"', 'id="model-form"',
        'id="model-key"', 'id="model-save"', 'id="model-clear"',
        'id="model-hint"', 'type="password"',
    ):
        assert token in html, token
    # 抽屉已改成整页，旧入口不应再出现
    for gone in ('id="chat-drawer"', 'id="chat-launcher"', 'id="chat-close"'):
        assert gone not in html, gone


def test_data_page_markup_has_datasource_segments_and_export():
    html = TestClient(app).get("/").text
    for token in (
        'id="view-data"', 'id="datasource"', 'id="datasource-chips"',
        'id="datasource-more"', 'id="tables-modal"', 'id="tables-body"',
        'id="tables-badge"', 'id="kpi-grid"', 'id="type-bars"',
        'id="ledger-counts"', 'id="data-seg"', 'id="seg-diffs"',
        'id="seg-ledgers"', 'id="panel-diffs"', 'id="panel-ledgers"',
        'id="export-btn"', 'id="export-note"', 'id="f-source"',
        'id="f-type"', 'id="f-side"', 'id="f-q"',
    ):
        assert token in html, token
    # 旧的三页拆分布局已被合并
    for gone in ('id="view-overview"', 'id="view-diffs"', 'id="view-ledgers"'):
        assert gone not in html, gone


def test_chat_script_wires_the_endpoints():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    for token in (
        "/api/chat/status", "/api/chat", "renderChat", "newChat",
        "/api/chat/presets", "renderChatSuggest", "buildChatArtifacts",
        "/api/chat/activity/", "activity_id", "buildChatSteps",
        "tool_steps", "model_calls", "sessionStorage",
        "/api/tables", "loadDatasource", "openTablesModal",
        "switchDataView", "exportCurrent", "/api/exports",
        "/api/model", "renderModelStatus", "saveModelKey", "clearModelKey",
    ):
        assert token in js, token
    # 默认路由是对话页，不再有聊天抽屉的开关逻辑
    assert '|| "chat"' in js
    for gone in ("setChatOpen", "closeChat", "chatState.open", "CHAT_QUICK"):
        assert gone not in js, gone


def test_styles_have_chat_page_and_data_hooks():
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    for token in (
        ".chat-page", ".chat-log", ".chat-msg--user", ".chat-compose",
        ".chat-source", ".chat-steps", ".chat-step", ".chat-step--running",
        ".chat-artifact", ".chat-suggest__chip", ".datasource", ".ds-chip",
        ".seg__btn", ".export-note", ".tables-row",
    ):
        assert token in css, token
