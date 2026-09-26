"""工作台服务：只读 JSON 接口 + 静态页。不写任何数据，不做任何计算性判断——
结论一律来自数据层/引擎层。"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.workbench import data
from src.workbench.contracts import DiffsPage, LedgerView, Overview

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


@app.get("/")
def index() -> FileResponse:
    return FileResponse(_STATIC / "index.html")


app.mount("/static", StaticFiles(directory=_STATIC), name="static")
