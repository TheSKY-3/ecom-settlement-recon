"""只读事实收集：5 个工具，产出喂给模型的"事实单"（也是白名单来源）。

复用 workbench 数据层（同一份已测代码）；findings 单条查询全量拉取后过滤并
剔除 evidence（那是引擎复核用的内部字段，不进提示词）。
"""
from __future__ import annotations

import json

from src.workbench import data

_EVIDENCE_FREE = ("finding_id", "order_id", "diff_type", "variant",
                  "target_side", "confidence", "description", "verified")


def order_facts(order_id: str) -> dict | None:
    led = data.load_ledger_by_order(order_id)
    if led is None:
        return None
    return {"kind": "order", "order_id": order_id, "gt": led["gt"],
            "bills": led["bills"], "payments": led["payments"],
            "refunds": led["refunds"], "order": led["orders"],
            "items": led["items"]}


def _findings_all() -> list[dict] | None:
    page = data.load_engine_diffs(None, None, None, page=1, page_size=10 ** 9)
    return None if page is None else page["rows"]


def _strip(row: dict) -> dict:
    return {k: row[k] for k in _EVIDENCE_FREE if k in row}


def finding(finding_id: str) -> dict | None:
    rows = _findings_all()
    if rows is None:
        return None
    hits = [r for r in rows if r["finding_id"] == finding_id]
    if not hits:
        return None
    f = _strip(hits[0])
    return {"kind": "finding", "finding": f,
            **(order_facts(f["order_id"]) or {"order_id": f["order_id"]})}


def gt(gt_id: str) -> dict | None:
    led = data.load_ledger(gt_id)
    if led is None:
        return None
    return {"kind": "gt", "gt": led["gt"], "bills": led["bills"],
            "payments": led["payments"], "refunds": led["refunds"],
            "order": led["orders"], "items": led["items"]}


def stats() -> dict | None:
    s = data.load_engine_summary()
    return {"kind": "stats", "score": s} if s else None


def samples_by_type(diff_type: str, limit: int = 3) -> dict | None:
    page = data.load_engine_diffs(diff_type, None, None, page=1, page_size=limit)
    if page is None:
        return None
    return {"kind": "samples", "diff_type": diff_type,
            "rows": [_strip(r) for r in page["rows"]]}
