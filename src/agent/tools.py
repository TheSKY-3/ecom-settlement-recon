"""只读事实收集：6 个工具，产出喂给模型的"事实单"（也是白名单来源）。

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


# 六类的固定顺序：输出稳定，前端与提示词都按这个顺序读。
DIFF_TYPES = ("单边账", "金额不符", "状态不一致", "退款遗漏", "重复结算", "版本差异")


def _all_findings() -> list[dict] | None:
    page = data.load_engine_diffs(None, None, None, page=1, page_size=10 ** 9)
    return None if page is None else page["rows"]


def type_stats() -> dict | None:
    """按类型/账本聚合：GT 数、发现数、TP/FN/FP、召回、两种精确率。

    口径与 evals/score.py 一致：命中按 (order_id, diff_type)；自然差异不计入
    precision_other（它是数据本身带的错，不是引擎判错），同时给出含自然差异的
    precision，方便用户看清"报了 1074 条里只有 500 条是真差异"这种观感。
    """
    findings = _all_findings()
    if findings is None:
        return None
    gt_rows = data.load_diffs(None, None, None, 1, 10 ** 9)["rows"]
    score = data.load_engine_summary() or {}
    gt_keys = {(r["order_id"], r["diff_type"]) for r in gt_rows}
    find_keys = {(f["order_id"], f["diff_type"]) for f in findings}
    fp_keys = find_keys - gt_keys
    # 自然差异优先取判分文件里的冻结口径；缺省时退化为"订单不在 GT 里"。
    natural_ids = score.get("fp_natural_ids")
    if not isinstance(natural_ids, list):
        gt_orders = {r["order_id"] for r in gt_rows}
        natural_ids = sorted({o for o, _ in fp_keys if o not in gt_orders})

    present = [t for t in DIFF_TYPES
               if any(k[1] == t for k in gt_keys | find_keys)]
    natural_set = set(natural_ids)
    by_type = []
    for dtype in present:
        tg = {k for k in gt_keys if k[1] == dtype}
        tf = {k for k in find_keys if k[1] == dtype}
        tp = len(tg & tf)
        fp = len(tf - tg)
        fp_natural = len({k for k in (tf - tg) if k[0] in natural_set})
        fp_other = fp - fp_natural
        by_type.append({
            "diff_type": dtype, "gt": len(tg), "findings": len(tf),
            "tp": tp, "fn": len(tg - tf), "fp": fp,
            "fp_natural": fp_natural, "fp_other": fp_other,
            "recall": round(tp / len(tg), 4) if tg else None,
            "precision": round(tp / len(tf), 4) if tf else None,
            "precision_other": (round(tp / (tp + fp_other), 4)
                                if (tp + fp_other) else None),
        })

    def _side(rows: list[dict]) -> dict:
        return {s: sum(1 for r in rows if r.get("target_side") == s)
                for s in ("bills", "payments", "refunds")}

    fp_total = len(fp_keys)
    fp_natural_total = len({k for k in fp_keys if k[0] in natural_set})
    tp_total = len(gt_keys & find_keys)
    return {
        "kind": "type_stats",
        "by_type": by_type,
        "by_side": {"gt": _side(gt_rows), "findings": _side(findings)},
        "totals": {
            "gt": len(gt_keys), "findings": len(find_keys),
            "tp": tp_total, "fn": len(gt_keys - find_keys), "fp": fp_total,
            "fp_natural": fp_natural_total, "fp_other": fp_total - fp_natural_total,
            "recall": round(tp_total / len(gt_keys), 4) if gt_keys else None,
            "precision": (round(tp_total / len(find_keys), 4)
                          if find_keys else None),
            "precision_other": (round(tp_total / (tp_total + fp_total - fp_natural_total), 4)
                                if (tp_total + fp_total - fp_natural_total) else None),
        },
    }
