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
from src.agent import llm
from src.workbench import data
from src.workbench.contracts import (
    AgentAnswer, AskRequest, DiffsPage, EnginePage, LedgerView, Overview, RowsPage)

app = FastAPI(title="对账工作台", docs_url="/api/docs")
_STATIC = Path(__file__).resolve().parent / "static"


@app.get("/api/overview", response_model=Overview)
def api_overview() -> dict:
    return data.load_overview()


@app.get("/api/diffs", response_model=DiffsPage)
def api_diffs(
    type: str | None = Query(None, description="差异类型，如：单边账"),
    side: str | None = Query(None, description="目标侧：bills/payments/refunds"),
    q: str | None = Query(None, description="搜订单号或描述"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> dict:
    return data.load_diffs(type, side, q, page, page_size)


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
) -> dict:
    page_data = data.load_engine_diffs(type, side, q, page, page_size)
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


@app.get("/")
def index() -> FileResponse:
    return FileResponse(_STATIC / "index.html")


app.mount("/static", StaticFiles(directory=_STATIC), name="static")
