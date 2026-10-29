"""判分：引擎发现 vs 标准答案。口径（injection-spec-v1）：
检出 TP = 命中 (order_id, diff_type)；漏检 FN = 答案有未报；误报 FP = 报了答案无，
FP 再按 P0 自然差异口径分桶（自然 / 其他）——自然差异是数据本身带的错，
测试集没给它们标准答案，如实报出不算引擎错。"""
from __future__ import annotations

DIFF_TYPES = ["单边账", "金额不符", "状态不一致", "退款遗漏", "重复结算", "版本差异"]


def score(gt_rows: list[dict], findings: list[dict], natural_ids: set[str]) -> dict:
    gt_keys = {(g["order_id"], g["diff_type"]) for g in gt_rows}
    find_keys = {(f["order_id"], f["diff_type"]) for f in findings}
    tp_keys = gt_keys & find_keys
    fn_keys = gt_keys - find_keys
    fp_keys = find_keys - gt_keys
    by_type = {}
    for dtype in DIFF_TYPES:
        t_g = {k for k in gt_keys if k[1] == dtype}
        t_f = {k for k in find_keys if k[1] == dtype}
        tp = len(t_g & t_f)
        by_type[dtype] = {"tp": tp, "fn": len(t_g - t_f), "fp": len(t_f - t_g),
                          "recall": round(tp / len(t_g), 4) if t_g else None}
    fp_natural = sorted(o for o, _ in fp_keys if o in natural_ids)
    fp_other = sorted([list(k) for k in fp_keys if k[0] not in natural_ids])
    return {
        "gt_total": len(gt_keys), "finding_total": len(find_keys),
        "tp": len(tp_keys), "fn": len(fn_keys), "fp": len(fp_keys),
        "fp_natural": len(fp_natural), "fp_natural_ids": fp_natural,
        "fp_other": len(fp_other), "fp_other_keys": fp_other,
        "recall": round(len(tp_keys) / len(gt_keys), 4) if gt_keys else None,
        "precision_other": (round(len(tp_keys) / (len(tp_keys) + len(fp_other)), 4)
                            if (tp_keys or fp_other) else None),
        "by_type": by_type,
    }
