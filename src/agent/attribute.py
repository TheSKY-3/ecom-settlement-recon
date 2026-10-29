"""出口一：attribute(ref) —— 对一条差异/订单做带证据的归因解释。"""
from __future__ import annotations

from src.agent import loop, prompts, tools

QUESTION = ("请解释这条差异：它是什么类型、证据在事实单的哪几行、"
            "可能的原因、建议的下一步。")


def attribute(ref: str) -> dict:
    facts = tools.finding(ref) or tools.gt(ref) or tools.order_facts(ref)
    if facts is None:
        return {"answer": f"找不到 {ref} 对应的差异、标准答案或订单。",
                "source": "fallback", "refs": [], "facts_sha256": None}
    return loop.run_once("attribute", ref, QUESTION, facts,
                         prompts.attribute_fallback(facts))
