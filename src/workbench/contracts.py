"""对外 JSON 契约：响应形状在这里定义，前端与后续 Agent 出口共用同一套口径。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class DiffRow(BaseModel):
    gt_id: str
    order_id: str
    diff_type: str
    variant: str
    target_side: str
    description: str


class DiffsPage(BaseModel):
    total: int
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=200)
    rows: list[DiffRow]


class LedgerView(BaseModel):
    gt: DiffRow | None          # 引擎报出的自然差异不在标准答案里 → gt 为空
    bills: list[dict]
    payments: list[dict]
    refunds: list[dict]
    orders: list[dict]
    items: list[dict]


class FindingRow(BaseModel):
    finding_id: str
    order_id: str
    diff_type: str
    variant: str
    target_side: str
    confidence: float
    description: str
    verified: bool


class EnginePage(BaseModel):
    total: int
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=200)
    rows: list[FindingRow]


class Overview(BaseModel):
    seed: int
    clean: dict[str, int]
    dirty: dict[str, int]
    gt: dict
