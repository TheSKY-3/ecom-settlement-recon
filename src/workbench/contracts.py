"""对外 JSON 契约：响应形状在这里定义，前端与后续 Agent 出口共用同一套口径。"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


def _empty_amount_none(v):
    """CSV 读回的空金额（旧考卷缺列）按 None 出，不报校验错。"""
    return None if v in ("", None) else v


class DiffRow(BaseModel):
    gt_id: str
    order_id: str
    diff_type: str
    variant: str
    target_side: str
    description: str
    amount: float | None = None   # 涉案金额（考卷 v1.2）；旧考卷缺列时为 None

    _amount = field_validator("amount", mode="before")(_empty_amount_none)


class DiffsPage(BaseModel):
    total: int
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=200)
    rows: list[DiffRow]


class LedgerView(BaseModel):
    gt: DiffRow | None          # 引擎报出的自然差异不在标准答案里 → gt 为空
    clean_bills: list[dict] = []     # 标准账本（应有的账）
    clean_payments: list[dict] = []
    clean_refunds: list[dict] = []
    bills: list[dict] = []           # 实际账本（埋错后的账）
    payments: list[dict] = []
    refunds: list[dict] = []
    orders: list[dict] = []          # 原始记录
    items: list[dict] = []
    # 原始订单库（data/olist.db）是否已加载；Docker 镜像默认不带，前端据此提示原因
    original_available: bool = True


class RowsPage(BaseModel):
    total: int
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=200)
    columns: list[str]
    rows: list[dict]


class FindingRow(BaseModel):
    finding_id: str
    order_id: str
    diff_type: str
    variant: str
    target_side: str
    confidence: float
    description: str
    amount: float | None = None   # 涉案金额（引擎发现现场复算）
    verified: bool

    _amount = field_validator("amount", mode="before")(_empty_amount_none)


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
    engine_money: dict | None = None   # 引擎发现涉案金额汇总；未跑引擎时为 None


class DataTable(BaseModel):
    key: str
    label: str
    role: str                   # 输入 | 参照 | 标准答案 | 产出
    rows: int
    columns: list[str]
    browse: str


class TablesResponse(BaseModel):
    seed: int
    tables: list[DataTable]
    gt_total: int
    engine_available: bool
    engine_run_id: str | None = None


class ChatSuggestion(BaseModel):
    text: str
    tools: list[dict] = Field(default_factory=list)


class ChatArtifact(BaseModel):
    file: str
    url: str
    format: str | None = None
    rows: int = 0
    orders: int = 0
    sheets: list[dict] = Field(default_factory=list)
    filters_text: str | None = None
    source: str | None = None


class AgentAnswer(BaseModel):
    answer: str
    source: str                  # "llm"（过白名单的 AI 文案）| "fallback"（确定性模板）
    refs: list[str]
    facts_sha256: str | None


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)


class ChatAskRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    session_id: str | None = Field(default=None, max_length=64)
    activity_id: str | None = Field(
        default=None, min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


class ChatToolStep(BaseModel):
    index: int = 0
    kind: str = "tool"          # tool | submit
    name: str = ""
    label: str
    args: dict[str, str] = Field(default_factory=dict)
    detail: str = ""
    status: str = "ok"          # running | ok | error
    duration_ms: int = 0


class ChatMessage(BaseModel):
    role: str
    content: str
    source: str | None = None
    refs: list[str] = Field(default_factory=list)
    tool_trace: list[str] = Field(default_factory=list)
    tool_steps: list[ChatToolStep] = Field(default_factory=list)
    model_calls: int = 0
    session_turns: int = 0
    reason: str | None = None
    artifacts: list[ChatArtifact] = Field(default_factory=list)
    suggestions: list[ChatSuggestion] = Field(default_factory=list)


class ChatTurnResponse(BaseModel):
    session_id: str
    status: str                 # ready | unavailable
    source: str                 # llm | fallback
    answer: str
    refs: list[str] = Field(default_factory=list)
    tool_trace: list[str] = Field(default_factory=list)
    tool_steps: list[ChatToolStep] = Field(default_factory=list)
    artifacts: list[ChatArtifact] = Field(default_factory=list)
    suggestions: list[ChatSuggestion] = Field(default_factory=list)
    model_calls: int = 0
    session_turns: int = 0
    reason: str | None = None


class ChatActivityResponse(BaseModel):
    activity_id: str
    done: bool = False
    steps: list[ChatToolStep] = Field(default_factory=list)


class ChatHistoryResponse(BaseModel):
    session_id: str
    messages: list[ChatMessage] = Field(default_factory=list)
    max_turns: int


class ChatStatusResponse(BaseModel):
    available: bool
    model: str
    max_turns: int
    max_message_chars: int


class ModelKeyRequest(BaseModel):
    api_key: str = Field(min_length=1, max_length=200)


class ModelStatus(BaseModel):
    provider: str = "deepseek"
    available: bool
    source: str | None = None      # override（页面输入）| env（环境变量）| None
    model: str
    key_hint: str | None = None    # 只回掩码，绝不回原文
