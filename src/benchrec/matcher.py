"""确定性匹配器：同币种+账户+金额精确分桶，桶内按日期贴近与参考号消歧。

保守决策（保精度）：候选为空 / 多键且参考号无法消歧 → 放弃匹配。
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date


def _parse_date(s: str) -> date | None:
    return date.fromisoformat(s[:10]) if s else None


def build_index(a_rows: list[dict]) -> dict:
    idx: dict[tuple, list[dict]] = defaultdict(list)
    for a in a_rows:
        key = (a["A_currencyCode"], a["A_account"], a["A_amount"])
        idx[key].append(a)
    return idx


def _allocations(cands: list[dict]) -> set[str]:
    return {c["A_allocation"] for c in cands if c["A_allocation"]}


def _ref_hit(b_refs: str, a_refs: str) -> bool:
    """B 参考号 token 被某 A 参考号包含 → 可消歧。"""
    return bool(b_refs) and b_refs in a_refs


def match(b_rows: list[dict], a_rows: list[dict],
          max_date_gap: int = 1) -> dict[str, frozenset[str]]:
    idx = build_index(a_rows)
    out: dict[str, frozenset[str]] = {}
    for b in b_rows:
        b_id = b["B_id"]
        cands = idx.get((b["B_currencyCode"], b["B_account"], b["B_amount"]), [])
        if not cands:
            out[b_id] = frozenset()
            continue
        b_date = _parse_date(b["B_valueDate"])
        dated = [(abs((_parse_date(c["A_valueDate"]) - b_date).days), c)
                 for c in cands if _parse_date(c["A_valueDate"]) and b_date]
        dated.sort(key=lambda t: t[0])
        best_gap, best = (dated[0][0], [c for g, c in dated if g == dated[0][0]]) \
            if dated else (None, [])
        if not best or best_gap > max_date_gap:
            out[b_id] = frozenset()
            continue
        keys = _allocations(best)
        if len(keys) == 1:
            out[b_id] = frozenset(keys)
            continue
        b_refs = b.get("B_transactionReferences", "")
        hits = {c["A_allocation"] for c in best if _ref_hit(b_refs, c.get("A_transactionReferences", ""))}
        out[b_id] = frozenset(hits) if len(hits) == 1 else frozenset()
    return out
