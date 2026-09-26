"""提示词与确定性文案。

系统提示只给一种自由：用事实单组织语言。fallback 文案同样从事实单取数，
所以"降级"和"AI 答案"享有同一个白名单，绝不出现无中生有的数字。
"""
from __future__ import annotations

import json

SYSTEM_PROMPT = (
    "你是对账助手。你只能使用用户消息中 JSON 事实单里的信息回答；"
    "不得引入事实单之外的任何数字或编号（含订单号、金额、日期、数量）；"
    "不得自己计算新的数字；事实单里没有的信息就说'事实单中未提供'。"
    "用简洁的中文面向财务同学回答，不超过 150 字。"
)

CAPABILITY_HINT = (
    "这个问题我答不了。我能查：①订单号（32 位编码）的对账情况；"
    "②差异编号（F 开头）或标准答案编号（GT 开头）的归因；"
    "③六类差异（单边账/金额不符/状态不一致/退款遗漏/重复结算/版本差异）"
    "的统计和例子；④引擎整体成绩。"
)


def _pct(x) -> str:
    return f"{x * 100:.1f}%"


def _shrink(rows: list[dict], n: int = 3) -> list[dict]:
    """事实单太长时截断，保证提示词小而准。"""
    return rows[:n]


def attribute_fallback(facts: dict) -> str:
    """无 AI 时的归因文案：全部数字取自事实单。"""
    parts = []
    f = facts.get("finding")
    g = facts.get("gt")
    if f:
        parts.append(f"差异 {f['finding_id']}：{f['description']}"
                     f"（{f['diff_type']} / {f['variant']}，"
                     f"置信度 {f['confidence']}）")
    elif g:
        parts.append(f"标准答案 {g['gt_id']}：{g['description']}"
                     f"（{g['diff_type']} / {g['variant']}）")
    oid = facts.get("order_id")
    if oid:
        parts.append(f"订单 {oid}：平台账单 {len(facts.get('bills', []))} 行、"
                     f"支付 {len(facts.get('payments', []))} 行、"
                     f"退款 {len(facts.get('refunds', []))} 行、"
                     f"订单明细 {len(facts.get('items', []))} 行")
    parts.append("以上为确定性摘要（AI 解释暂不可用）；"
                 "证据明细可在工作台点开该差异查看五本账对照。")
    return "；".join(parts) + "。"


def stats_fallback(score: dict) -> str:
    g = score.get
    return (
        f"引擎共报 {g('finding_total', '—')} 条发现；对照标准答案 "
        f"{g('gt_total', '—')} 颗，命中 {g('tp', '—')}、漏检 {g('fn', '—')}、"
        f"召回 {_pct(g('recall', 0.0))}；误报 {g('fp', '—')} 条中"
        f"自然差异 {g('fp_natural', '—')} 条、真误报 {g('fp_other', '—')} 条"
        f"（精确率 {_pct(g('precision_other', 0.0))}）。"
        "自然差异 = 数据自带的问题，测试集未给标准答案，单独统计不计误报。"
    )


def samples_fallback(rows: list[dict]) -> str:
    if not rows:
        return "该类型暂无引擎发现。"
    lines = [f"- {r['finding_id']}（订单 {r['order_id']}）：{r['description']}"
             for r in rows]
    return "该类型的例子：\n" + "\n".join(lines)


def facts_json(facts: dict, max_rows: int = 6) -> str:
    """事实单压缩：每段最多 max_rows 行，控制提示词体积。"""
    slim = {}
    for k, v in facts.items():
        if isinstance(v, list):
            slim[k] = _shrink(v, max_rows)
        else:
            slim[k] = v
    return json.dumps(slim, ensure_ascii=False, sort_keys=True)
