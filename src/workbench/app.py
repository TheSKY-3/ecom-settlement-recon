"""工作台服务：只读 JSON 接口 + 静态页。不写任何数据，不做任何计算性判断——
结论一律来自数据层/引擎层。"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.agent import ask as agent_ask
from src.agent import attribute as agent_attribute
from src.agent import chat as agent_chat
from src.agent import llm, suggestions
from src.workbench import data
from src.workbench import export as export_mod
from src.workbench.contracts import (
    AgentAnswer, AskRequest, ChatActivityResponse, ChatAskRequest, ChatHistoryResponse,
    ChatStatusResponse, ChatTurnResponse, DiffsPage, EnginePage, LedgerView, ModelKeyRequest,
    ModelStatus, Overview, RowsPage, TablesResponse)

app = FastAPI(title="对账工作台", docs_url="/api/docs")
_STATIC = Path(__file__).resolve().parent / "static"
_CHAT = agent_chat.ChatService()


@app.get("/api/overview", response_model=Overview)
def api_overview() -> dict:
    return data.load_overview()


@app.get("/api/tables", response_model=TablesResponse)
def api_tables() -> dict:
    return data.load_tables()


@app.get("/api/diffs", response_model=DiffsPage)
def api_diffs(
    type: str | None = Query(None, description="差异类型，如：单边账"),
    side: str | None = Query(None, description="目标侧：bills/payments/refunds"),
    q: str | None = Query(None, description="搜订单号或描述"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    sort: str | None = Query(None, description="排序：amount_desc=涉案金额从大到小"),
) -> dict:
    return data.load_diffs(type, side, q, page, page_size, sort=sort)


@app.get("/api/diffs/{gt_id}/ledger", response_model=LedgerView)
def api_ledger(gt_id: str) -> dict:
    led = data.load_ledger(gt_id)
    if led is None:
        raise HTTPException(status_code=404, detail=f"标准答案里没有 {gt_id}")
    return led


@app.get("/api/ledger/order/{order_id}", response_model=LedgerView)
def api_ledger_by_order(order_id: str) -> dict:
    led = data.load_ledger_by_order(order_id)
    if led is None:
        raise HTTPException(status_code=404, detail=f"任何账本里都没有订单 {order_id}")
    return led


@app.get("/api/engine")
def api_engine() -> dict:
    summary = data.load_engine_summary()
    if summary is None:
        return {"available": False, "hint": "先跑 scripts/run_engine.py 生成 output/engine/"}
    return {"available": True, "score": summary}


@app.get("/api/engine/findings", response_model=EnginePage)
def api_engine_findings(
    type: str | None = Query(None, description="差异类型"),
    side: str | None = Query(None, description="目标侧：bills/payments/refunds"),
    q: str | None = Query(None, description="搜订单号或描述"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    sort: str | None = Query(None, description="排序：amount_desc=涉案金额从大到小"),
) -> dict:
    page_data = data.load_engine_diffs(type, side, q, page, page_size, sort=sort)
    if page_data is None:
        raise HTTPException(status_code=404, detail="引擎尚未运行：先跑 scripts/run_engine.py")
    return page_data


@app.get("/api/agent/status")
def api_agent_status() -> dict:
    return {"available": llm.available(),
            "model": os.environ.get("RECON_AGENT_MODEL", llm.DEFAULT_MODEL)}


@app.post("/api/agent/ask", response_model=AgentAnswer)
def api_agent_ask(body: AskRequest) -> dict:
    return agent_ask.ask(body.question)


@app.get("/api/agent/attribute/{ref}", response_model=AgentAnswer)
def api_agent_attribute(ref: str) -> dict:
    return agent_attribute.attribute(ref)


def _model_status() -> dict:
    return {"provider": "deepseek",
            "available": llm.available(),
            "source": llm.key_source(),
            "model": os.environ.get("RECON_AGENT_MODEL", llm.DEFAULT_MODEL),
            "key_hint": llm.key_hint()}


@app.get("/api/model", response_model=ModelStatus)
def api_model_status() -> dict:
    """当前 key 来源与掩码；绝不返回 key 原文。"""
    return _model_status()


@app.post("/api/model", response_model=ModelStatus)
def api_model_set(body: ModelKeyRequest) -> dict:
    """页面里输入 key：先做一次最小调用验证，通过才生效。只存进程内存。"""
    key = body.api_key.strip()
    if len(key) < 8:
        raise HTTPException(status_code=400, detail="key 太短：粘贴完整的一串")
    try:
        llm.probe(key)
    except llm.LLMError as e:
        raise HTTPException(status_code=400, detail=str(e))
    llm.set_api_key(key)
    return _model_status()


@app.delete("/api/model", response_model=ModelStatus)
def api_model_clear() -> dict:
    """清掉页面输入的 key，回落到环境变量（若设置了）。"""
    llm.set_api_key(None)
    return _model_status()


@app.get("/api/chat/status", response_model=ChatStatusResponse)
def api_chat_status() -> dict:
    return _CHAT.status()


@app.get("/api/chat/presets")
def api_chat_presets() -> dict:
    return {"presets": suggestions.PRESETS}


@app.get("/api/chat/activity/{activity_id}", response_model=ChatActivityResponse)
def api_chat_activity(activity_id: str) -> dict:
    try:
        return _CHAT.activity(activity_id)
    except agent_chat.ChatActivityNotFound:
        raise HTTPException(status_code=404, detail="执行过程不存在或已过期")


@app.post("/api/chat", response_model=ChatTurnResponse)
def api_chat(body: ChatAskRequest) -> dict:
    try:
        result = _CHAT.turn(body.session_id, body.message, body.activity_id)
    except agent_chat.ChatInputError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except agent_chat.ChatSessionNotFound:
        raise HTTPException(status_code=404, detail="会话不存在或已过期，请新开对话")
    return {
        "session_id": result.session_id,
        "status": result.status,
        "source": result.source,
        "answer": result.answer,
        "refs": result.refs,
        "tool_trace": result.tool_trace,
        "tool_steps": result.tool_steps,
        "artifacts": result.artifacts,
        "suggestions": result.suggestions,
        "model_calls": result.model_calls,
        "session_turns": result.session_turns,
        "reason": result.reason,
    }


@app.get("/api/chat/{session_id}", response_model=ChatHistoryResponse)
def api_chat_history(session_id: str) -> dict:
    try:
        messages = _CHAT.history(session_id)
    except agent_chat.ChatSessionNotFound:
        raise HTTPException(status_code=404, detail="会话不存在或已过期")
    return {"session_id": session_id, "messages": messages,
            "max_turns": _CHAT.max_turns}


@app.delete("/api/chat/{session_id}")
def api_chat_reset(session_id: str) -> dict:
    if not _CHAT.reset(session_id):
        raise HTTPException(status_code=404, detail="会话不存在或已过期")
    return {"session_id": session_id, "reset": True}


@app.get("/api/rows/{world}/{book}", response_model=RowsPage)
def api_rows(
    world: str,
    book: str,
    q: str | None = Query(None, description="任意字段关键词"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> dict:
    try:
        return data.load_rows(world, book, q, page, page_size)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/exports")
def api_export(body: export_mod.ExportRequest) -> dict:
    """数据页“导出当前筛选”的入口；与对话工具共用同一生成器。"""
    try:
        return export_mod.create_export(body)
    except export_mod.ExportError as e:
        raise HTTPException(status_code=400, detail=f"{e.code}: {e.message}")


@app.get("/api/exports/{token}")
def api_export_file(token: str) -> FileResponse:
    meta = export_mod.resolve(token)
    if meta is None:
        raise HTTPException(status_code=404, detail="导出文件不存在或已过期（有效期 30 分钟）")
    return FileResponse(
        path=meta["path"], filename=meta["file"],
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(_STATIC / "index.html")


app.mount("/static", StaticFiles(directory=_STATIC), name="static")
