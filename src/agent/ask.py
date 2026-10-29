"""出口二：ask(question) —— 自然语言查账。

意图路由是确定性的：能确定性回答的（统计/例子）用模板直答不花模型调用；
只有"归因解释"类（订单/编号命中）才进模型循环；都没有则给能力话术。
"""
from __future__ import annotations

import re

from src.agent import attribute, guardrails, llm, loop, prompts, tools

ORDER_ID_RE = guardrails.ORDER_ID_RE
GT_RE = guardrails.GT_RE
FINDING_RE = guardrails.FINDING_RE
STATS_WORDS = ("多少", "几条", "统计", "分布", "成绩", "召回", "准确", "跑分")
TYPE_NAMES = ("单边账", "金额不符", "状态不一致", "退款遗漏", "重复结算", "版本差异")


def _stats_answer() -> dict:
    s = tools.stats()
    if s is None:
        return {"answer": "引擎尚未运行：先跑 scripts/run_engine.py 生成判定结果。",
                "source": "fallback", "refs": [], "facts_sha256": None}
    return {"answer": prompts.stats_fallback(s["score"]), "source": "fallback",
            "refs": [], "facts_sha256": None}


def ask(question: str) -> dict:
    if (m := ORDER_ID_RE.search(question)) and (facts := tools.order_facts(m.group(0))):
        return loop.run_once("ask", m.group(0), "解释这个订单的对账情况。", facts,
                             prompts.attribute_fallback(facts))
    if (m := FINDING_RE.search(question)) or (m := GT_RE.search(question)):
        return attribute.attribute(m.group(0))
    for name in TYPE_NAMES:
        if name in question:
            head = prompts.stats_fallback(tools.stats()["score"]) \
                if tools.stats() else ""
            samples = tools.samples_by_type(name)
            body = prompts.samples_fallback(samples["rows"]) if samples else ""
            return {"answer": (head + "\n" + body).strip(),
                    "source": "fallback", "refs": [], "facts_sha256": None}
    if any(w in question for w in STATS_WORDS):
        return _stats_answer()
    return {"answer": prompts.CAPABILITY_HINT, "source": "fallback",
            "refs": [], "facts_sha256": None}
