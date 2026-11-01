"""确定性 Excel 导出（D016）：对话与数据页共用同一个生成器。

边界：
- 只导出差异对照（标准答案 ↔ 引擎发现 ∪ 订单汇总），不导出 10 万行源表；
- 行和数全部由本模块按数据层计算，模型只能挑筛选条件，不能写单元格；
- 生成物落在 RECON_EXPORT_DIR（默认 output/exports/），带随机 token + TTL；
- 单元格文本做公式注入防护，金额/置信度为数值格式，便于筛选与透视。
"""
from __future__ import annotations

import os
import re
import threading
import time
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.workbench import data

EXPORT_TTL_S = 30 * 60
MAX_EXPORT_ROWS = 5000
MAX_REGISTRY = 200

SIDE_LABEL = {"bills": "账单", "payments": "支付", "refunds": "退款"}

DETAIL_SHEET = "对照明细"
SUMMARY_SHEET = "订单汇总"

DETAIL_HEADERS = [
    "标准答案编号", "引擎发现编号", "订单号", "差异类型", "变体", "所在账本",
    "匹配状态", "标准答案描述", "引擎描述", "置信度", "复核状态", "涉案金额",
    "账单笔数", "账单结算额", "支付笔数", "支付额", "退款笔数", "退款额", "差异备注",
]
SUMMARY_HEADERS = [
    "订单号", "差异条数", "差异类型", "涉案金额", "标准答案条数", "引擎发现条数",
    "最高置信度",
    "账单笔数", "账单结算额", "支付笔数", "支付额", "退款笔数", "退款额", "明细编号",
]

MONEY_COLUMNS = {"涉案金额", "账单结算额", "支付额", "退款额"}
INT_COLUMNS = {"账单笔数", "支付笔数", "退款笔数", "差异条数", "标准答案条数", "引擎发现条数"}
CONF_COLUMNS = {"置信度", "最高置信度"}

# 不同列的显示宽度；openpyxl 里 1 个单位约等于 1 个字符
COL_WIDTH = {
    "标准答案编号": 13, "引擎发现编号": 12, "订单号": 34, "差异类型": 11,
    "变体": 16, "所在账本": 9, "匹配状态": 22, "标准答案描述": 44,
    "引擎描述": 44, "置信度": 8, "复核状态": 9, "涉案金额": 11, "差异备注": 30,
    "差异条数": 9, "标准答案条数": 11, "引擎发现条数": 11, "最高置信度": 10,
    "明细编号": 26,
}


class ExportError(RuntimeError):
    """导出失败；code 用于对话工具事实与接口错误码。"""

    def __init__(self, code: str, message: str = ""):
        self.code = code
        self.message = message or code
        super().__init__(self.message)


class ExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: Literal["gt", "engine", "both"] = "both"
    diff_type: Literal["单边账", "金额不符", "状态不一致", "退款遗漏",
                        "重复结算", "版本差异"] | None = None
    side: Literal["bills", "payments", "refunds"] | None = None
    q: str | None = Field(default=None, max_length=64)
    sort: Literal["amount_desc"] | None = None
    # 以下过滤只看引擎发现：标准答案没有置信度/复核/自然差异概念
    min_confidence: float | None = Field(default=None, ge=0, le=1)
    max_confidence: float | None = Field(default=None, ge=0, le=1)
    verified: bool | None = None
    natural_only: bool = False


def _export_dir() -> Path:
    return Path(os.environ.get(
        "RECON_EXPORT_DIR",
        Path(__file__).resolve().parents[2] / "output" / "exports"))


def _money(value) -> float:
    try:
        return round(float(value or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def _key(row: dict) -> tuple:
    return (row["order_id"], row["diff_type"], row["target_side"])


def _q_match(row: dict, needle: str) -> bool:
    return (needle in row["order_id"].lower()
            or needle in (row.get("description") or "").lower())


def _engine_filters(args: ExportRequest) -> bool:
    return (args.min_confidence is not None or args.max_confidence is not None
            or args.verified is not None or args.natural_only)


def _filter_gt(rows: list[dict], args: ExportRequest) -> list[dict]:
    if args.diff_type:
        rows = [r for r in rows if r["diff_type"] == args.diff_type]
    if args.side:
        rows = [r for r in rows if r["target_side"] == args.side]
    if args.q:
        needle = args.q.lower()
        rows = [r for r in rows if _q_match(r, needle)]
    return rows


def _filter_findings(rows: list[dict], args: ExportRequest,
                     gt_orders: set[str]) -> list[dict]:
    if args.diff_type:
        rows = [r for r in rows if r["diff_type"] == args.diff_type]
    if args.side:
        rows = [r for r in rows if r["target_side"] == args.side]
    if args.q:
        needle = args.q.lower()
        rows = [r for r in rows if _q_match(r, needle)]
    if args.min_confidence is not None:
        rows = [r for r in rows if float(r.get("confidence") or 0) >= args.min_confidence]
    if args.max_confidence is not None:
        rows = [r for r in rows if float(r.get("confidence") or 0) <= args.max_confidence]
    if args.verified is not None:
        rows = [r for r in rows if bool(r.get("verified")) is args.verified]
    if args.natural_only:
        rows = [r for r in rows if r["order_id"] not in gt_orders]
    return rows


def _ledger_index() -> dict:
    """订单 → 三本账的（笔数, 金额, 版本摘要）；一次扫描，供几千行复用。"""
    bills = defaultdict(lambda: {"count": 0, "amount": 0.0, "versions": set()})
    for row in data.side_rows("dirty", "platform_bills"):
        item = bills[row["order_id"]]
        item["count"] += 1
        item["amount"] += _money(row.get("settlement_amount"))
        item["versions"].add(str(row.get("version") or ""))
    payments = defaultdict(lambda: {"count": 0, "amount": 0.0})
    for row in data.side_rows("dirty", "order_payments"):
        item = payments[row["order_id"]]
        item["count"] += 1
        item["amount"] += _money(row.get("payment_value"))
    refunds = defaultdict(lambda: {"count": 0, "amount": 0.0})
    for row in data.side_rows("dirty", "refunds"):
        item = refunds[row["order_id"]]
        item["count"] += 1
        item["amount"] += _money(row.get("refund_amount"))
    return {"bills": bills, "payments": payments, "refunds": refunds}


def _evidence(index: dict, order_id: str) -> dict:
    bill = index["bills"].get(order_id) or {"count": 0, "amount": 0.0, "versions": set()}
    pay = index["payments"].get(order_id) or {"count": 0, "amount": 0.0}
    ref = index["refunds"].get(order_id) or {"count": 0, "amount": 0.0}
    versions = sorted(v for v in bill.get("versions") or [] if v)
    return {
        "账单笔数": int(bill["count"]),
        "账单结算额": _money(bill["amount"]),
        "支付笔数": int(pay["count"]),
        "支付额": _money(pay["amount"]),
        "退款笔数": int(ref["count"]),
        "退款额": _money(ref["amount"]),
        "账单版本": "、".join(versions),
    }


def _remark(diff_type: str, side: str, matched: bool, evidence: dict) -> str:
    where = SIDE_LABEL.get(side, side)
    if matched:
        base = f"标准答案与引擎一致（{where}侧）"
    elif evidence["账单笔数"] == 0 and side == "bills":
        base = f"引擎未报这项{diff_type}；账单侧无记录"
    else:
        base = f"引擎未报这项{diff_type}（{where}侧）"
    if diff_type == "版本差异" and evidence["账单版本"]:
        return f"{base}；账单版本 {evidence['账单版本']}"
    return base


def _build_detail_rows(args: ExportRequest) -> tuple[list[dict], dict]:
    gt_rows = data.gt_rows()
    try:
        finding_rows = data.findings_rows()
    except FileNotFoundError:
        if args.source != "gt":
            raise ExportError("ENGINE_UNAVAILABLE",
                              "引擎发现未生成：先跑 scripts/run_engine.py") from None
        finding_rows = []
    if args.source == "gt" and _engine_filters(args):
        raise ExportError("INVALID_ARGS",
                          "min_confidence/max_confidence/verified/natural_only 只对引擎发现有效")
    gt_map = {_key(r): r for r in gt_rows}
    find_map = {_key(r): r for r in finding_rows}
    gt_orders = {r["order_id"] for r in gt_rows}
    index = _ledger_index()

    def pair_row(gt: dict | None, finding: dict | None) -> dict:
        base = gt or finding or {}
        order_id = base["order_id"]
        side = base["target_side"]
        diff_type = base["diff_type"]
        matched = bool(gt and finding)
        if matched:
            status = "一致"
        elif gt:
            status = "仅标准答案（引擎未报）"
        else:
            status = "仅引擎（自然差异/误报）"
        evidence = _evidence(index, order_id)
        return {
            "标准答案编号": gt["gt_id"] if gt else "",
            "引擎发现编号": finding["finding_id"] if finding else "",
            "订单号": order_id,
            "差异类型": diff_type,
            "变体": (gt or finding).get("variant") or "",
            "所在账本": SIDE_LABEL.get(side, side),
            "匹配状态": status,
            "标准答案描述": gt["description"] if gt else "",
            "引擎描述": finding["description"] if finding else "",
            "置信度": float(finding["confidence"]) if finding else None,
            "复核状态": ("已复核" if finding.get("verified") else "未复核") if finding else "",
            # 涉案金额：优先标准答案口径（注入时记录），自然差异只有引擎口径；
            # 两者经判分器逐条对账一致（见 score.json 的 amount_consistency）
            "涉案金额": _money((gt or finding).get("amount")),
            "账单笔数": evidence["账单笔数"],
            "账单结算额": evidence["账单结算额"],
            "支付笔数": evidence["支付笔数"],
            "支付额": evidence["支付额"],
            "退款笔数": evidence["退款笔数"],
            "退款额": evidence["退款额"],
            "差异备注": _remark(diff_type, side, matched, evidence),
        }

    rows: list[dict] = []
    if args.source == "gt":
        for gt in _filter_gt(gt_rows, args):
            rows.append(pair_row(gt, find_map.get(_key(gt))))
    elif args.source == "engine":
        for finding in _filter_findings(finding_rows, args, gt_orders):
            rows.append(pair_row(gt_map.get(_key(finding)), finding))
    else:  # both：以引擎发现为骨架，再补“引擎完全没报”的标准答案（本数据集为 0）
        for finding in _filter_findings(finding_rows, args, gt_orders):
            rows.append(pair_row(gt_map.get(_key(finding)), finding))
        for gt in _filter_gt(gt_rows, args):
            if _key(gt) not in find_map:
                rows.append(pair_row(gt, None))
    if args.sort:
        if args.sort != "amount_desc":
            raise ExportError("INVALID_ARGS", f"未知排序：{args.sort}（支持 amount_desc）")
        rows.sort(key=lambda r: r["涉案金额"] or 0, reverse=True)
    return rows, index


def _build_summary_rows(rows: list[dict], index: dict) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[row["订单号"]].append(row)
    summary = []
    for order_id in sorted(grouped):
        group = grouped[order_id]
        types = list(dict.fromkeys(r["差异类型"] for r in group))
        confs = [r["置信度"] for r in group if r["置信度"] is not None]
        evidence = _evidence(index, order_id)
        ids = [r["标准答案编号"] or r["引擎发现编号"] for r in group]
        summary.append({
            "订单号": order_id,
            "差异条数": len(group),
            "差异类型": "、".join(types),
            "涉案金额": _money(sum(r["涉案金额"] or 0 for r in group)),
            "标准答案条数": sum(1 for r in group if r["标准答案编号"]),
            "引擎发现条数": sum(1 for r in group if r["引擎发现编号"]),
            "最高置信度": max(confs) if confs else None,
            "账单笔数": evidence["账单笔数"],
            "账单结算额": evidence["账单结算额"],
            "支付笔数": evidence["支付笔数"],
            "支付额": evidence["支付额"],
            "退款笔数": evidence["退款笔数"],
            "退款额": evidence["退款额"],
            "明细编号": "、".join(ids),
        })
    return summary


_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _cell_value(value):
    """清洗非法字符；以 = 开头的文本强制按字符串写，避免被 Excel 当公式执行。"""
    if value is None:
        return None
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (int, float)):
        return value
    text = _CTRL_RE.sub("", str(value))
    if len(text) > 500:
        text = text[:499] + "…"
    return text


def _style_sheet(ws, headers: list[str], widths: dict) -> None:
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    header_font = Font(name="微软雅黑", bold=True, color="FFFFFF", size=10)
    header_fill = PatternFill("solid", fgColor="0F766E")
    body_font = Font(name="微软雅黑", size=10)
    for col, title in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col, value=title)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.column_dimensions[get_column_letter(col)].width = widths.get(title, 14)
        for row in ws.iter_rows(min_row=2, min_col=col, max_col=col):
            row[0].font = body_font
    ws.row_dimensions[1].height = 22
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{max(ws.max_row, 1)}"


def _write_workbook(path: Path, rows: list[dict], summary: list[dict],
                    meta: dict) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment

    wb = Workbook()
    detail = wb.active
    detail.title = DETAIL_SHEET
    detail.append(DETAIL_HEADERS)
    for row in rows:
        detail.append([_cell_value(row.get(h)) for h in DETAIL_HEADERS])
    _style_sheet(detail, DETAIL_HEADERS, COL_WIDTH)
    for row in detail.iter_rows(min_row=2):
        for cell in row:
            header = DETAIL_HEADERS[cell.column - 1]
            if header in MONEY_COLUMNS:
                cell.number_format = "#,##0.00"
            elif header in CONF_COLUMNS:
                cell.number_format = "0.00"
            elif header in INT_COLUMNS:
                cell.number_format = "0"
            elif header in ("订单号", "标准答案编号", "引擎发现编号"):
                cell.number_format = "@"
            if header in ("标准答案描述", "引擎描述", "差异备注", "匹配状态"):
                cell.alignment = Alignment(vertical="top", wrap_text=True)

    book = wb.create_sheet(SUMMARY_SHEET)
    book.append(SUMMARY_HEADERS)
    for row in summary:
        book.append([_cell_value(row.get(h)) for h in SUMMARY_HEADERS])
    _style_sheet(book, SUMMARY_HEADERS, COL_WIDTH)
    for row in book.iter_rows(min_row=2):
        for cell in row:
            header = SUMMARY_HEADERS[cell.column - 1]
            if header in MONEY_COLUMNS:
                cell.number_format = "#,##0.00"
            elif header in CONF_COLUMNS:
                cell.number_format = "0.00"
            elif header in INT_COLUMNS:
                cell.number_format = "0"
            elif header == "订单号":
                cell.number_format = "@"
            if header in ("差异类型", "明细编号"):
                cell.alignment = Alignment(vertical="top", wrap_text=True)
    # 以 = 开头的文本必须按字符串存，防止 Excel 打开时当公式执行
    for sheet in (detail, book):
        for row in sheet.iter_rows():
            for cell in row:
                if isinstance(cell.value, str) and cell.value.startswith("="):
                    cell.data_type = "s"
    # 说明放在文档属性里：工作表只留两张纯数据表，方便直接筛选/透视
    props = wb.properties
    props.title = meta.get("file") or "对账差异对照"
    props.subject = "电商结算对账 · 差异对照表"
    props.description = (
        f"来源={meta.get('source')}；筛选={meta.get('filters_text') or '无'}；"
        f"明细 {len(rows)} 行 / 订单 {len(summary)} 个；"
        f"数据批次 seed={meta.get('seed')}；"
        f"引擎 run_id={meta.get('run_id') or '未运行'}；"
        f"生成时间={meta.get('created_text')}")
    props.creator = "对账工作台"
    wb.save(path)


def _safe_name(text: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|\s]+', "_", str(text)).strip("_")
    return cleaned[:60] or "对照表"


def _filters_text(args: ExportRequest) -> str:
    parts = []
    if args.source == "gt":
        parts.append("仅标准答案")
    elif args.source == "engine":
        parts.append("仅引擎发现")
    if args.diff_type:
        parts.append(args.diff_type)
    if args.side:
        parts.append(SIDE_LABEL.get(args.side, args.side) + "侧")
    if args.q:
        parts.append("关键词")
    if args.min_confidence is not None:
        parts.append(f"置信度≥{args.min_confidence}")
    if args.max_confidence is not None:
        parts.append(f"置信度≤{args.max_confidence}")
    if args.verified is not None:
        parts.append("已复核" if args.verified else "未复核")
    if args.natural_only:
        parts.append("仅自然差异")
    return "，".join(parts) or "全部差异"


def filters_fact(args: ExportRequest) -> dict:
    """回显生效的筛选：数字阈值可以进白名单，用户输入的关键词不回显。"""
    out = {"source": args.source}
    if args.diff_type:
        out["diff_type"] = args.diff_type
    if args.side:
        out["side"] = args.side
    if args.min_confidence is not None:
        out["min_confidence"] = args.min_confidence
    if args.max_confidence is not None:
        out["max_confidence"] = args.max_confidence
    if args.verified is not None:
        out["verified"] = args.verified
    if args.natural_only:
        out["natural_only"] = True
    return out


_registry: dict[str, dict] = {}
_lock = threading.Lock()


def _drop_locked(token: str) -> None:
    meta = _registry.pop(token, None)
    if not meta:
        return
    try:
        Path(meta["path"]).unlink(missing_ok=True)
    except OSError:
        pass


def _cleanup_locked(now: float) -> None:
    for token, meta in list(_registry.items()):
        if now - meta["created"] > EXPORT_TTL_S:
            _drop_locked(token)
    while len(_registry) > MAX_REGISTRY:
        oldest = min(_registry, key=lambda t: _registry[t]["created"])
        _drop_locked(oldest)


def create_export(payload: dict | ExportRequest) -> dict:
    """校验筛选 → 算行 → 写 xlsx → 登记 token；返回可放进事实/前端的元数据。"""
    if isinstance(payload, ExportRequest):
        args = payload
    else:
        try:
            args = ExportRequest.model_validate(payload or {})
        except ValidationError as e:
            raise ExportError("INVALID_ARGS", str(e)[:160]) from None
    rows, index = _build_detail_rows(args)
    if not rows:
        raise ExportError("NO_ROWS", "当前筛选没有可导出的差异")
    if len(rows) > MAX_EXPORT_ROWS:
        raise ExportError("TOO_MANY_ROWS",
                          f"导出上限 {MAX_EXPORT_ROWS} 行，请缩小筛选范围")
    summary = _build_summary_rows(rows, index)
    score = data.load_engine_summary() or {}
    now = time.time()
    seed = data.load_overview().get("seed")
    filters_text = _filters_text(args)
    name = (f"对账对照_{_safe_name(filters_text)}_"
            f"{time.strftime('%Y%m%d_%H%M%S', time.localtime(now))}.xlsx")
    out_dir = _export_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    path = out_dir / f"{token}_{name}"
    meta = {
        "file": name, "source": args.source, "filters_text": filters_text,
        "seed": seed, "run_id": score.get("run_id"),
        "created_text": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
        "filters": filters_fact(args),
    }
    _write_workbook(path, rows, summary, meta)
    preview: list[dict] = []
    for row in rows[:5]:
        preview.append({k: row[k] for k in DETAIL_HEADERS
                        if row[k] not in (None, "")})
    with _lock:
        _cleanup_locked(now)
        _registry[token] = {"path": str(path), "file": name,
                            "created": now, "rows": len(rows),
                            "orders": len(summary)}
        # 清掉目录里过期但不在登记表的残留（例如进程重启前生成的）
        try:
            for old in out_dir.glob("*.xlsx"):
                if old.stat().st_mtime > 0 and now - old.stat().st_mtime > EXPORT_TTL_S:
                    old.unlink(missing_ok=True)
        except OSError:
            pass
    return {
        "kind": "export", "format": "xlsx", "file": name,
        "url": f"/api/exports/{token}", "token": token,
        "source": args.source, "filters": meta["filters"],
        "filters_text": filters_text,
        "rows": len(rows), "orders": len(summary),
        "sheets": [{"name": DETAIL_SHEET, "rows": len(rows)},
                   {"name": SUMMARY_SHEET, "rows": len(summary)}],
        "preview": preview,
        "seed": seed, "run_id": score.get("run_id"),
        "created": meta["created_text"],
    }


def resolve(token: str) -> dict | None:
    """按 token 取登记信息；过期即删文件并返回 None。"""
    now = time.time()
    with _lock:
        _cleanup_locked(now)
        meta = _registry.get(token)
        if meta is None:
            return None
        path = Path(meta["path"])
        if not path.is_file():
            _drop_locked(token)
            return None
        return dict(meta)


def export_path(token: str) -> Path | None:
    meta = resolve(token)
    return Path(meta["path"]) if meta else None


def cleanup() -> None:
    """测试/维护用：清空登记表与生成物。"""
    with _lock:
        for token in list(_registry):
            _drop_locked(token)
