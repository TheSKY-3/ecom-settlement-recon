"""护栏一：输出白名单校验。

模型输出里的每个数字、每个编号（订单/GT/发现/账单/退款）都必须能在本次喂给它的
事实单里找到；找不到即判违规。百分比按 x÷100 等价放行（score 里 1.0 → "100%"），
千分位写法等价放行。日期整体提取（不拆成年月日数字），日期字符串本身入允许集。
"""
from __future__ import annotations

import re

DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}:\d{2})?")
NUM_RE = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?")
# 用环视而非 \b：Python 的 \w 视中文为词字符，"订单abcd…" 处 \b 不成立。
ORDER_ID_RE = re.compile(r"(?<![0-9a-f])[0-9a-f]{32}(?![0-9a-f])")
GT_RE = re.compile(r"(?<![0-9A-Za-z])GT\d+(?![0-9A-Za-z])")
FINDING_RE = re.compile(r"(?<![0-9A-Za-z])F\d{6}(?![0-9A-Za-z])")
BILL_ID_RE = re.compile(r"(?<![0-9A-Za-z])B_[0-9a-f]{32}_\d+(?![0-9A-Za-z])")
REFUND_ID_RE = re.compile(r"(?<![0-9A-Za-z])R_[0-9a-f]{32}_\d+(?![0-9A-Za-z])")
ID_RES = (ORDER_ID_RE, GT_RE, FINDING_RE, BILL_ID_RE, REFUND_ID_RE)


def _walk(obj):
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)
    else:
        yield obj


def _num_variants(x: float) -> set[str]:
    out = set()
    for v in (x, x * 100, x / 100):
        out |= {f"{v:g}", f"{v:.2f}", f"{v:,.2f}", f"{v:,.0f}"}
    return out


def allowed_values(facts) -> tuple[set[str], set[str]]:
    """返回（允许的数字串, 允许的编号）集合。"""
    nums: set[str] = set()
    ids: set[str] = set()
    for leaf in _walk(facts):
        if isinstance(leaf, (int, float)) and not isinstance(leaf, bool):
            nums |= _num_variants(float(leaf))
            continue
        if not isinstance(leaf, str):
            continue
        for m in DATE_RE.finditer(leaf):
            nums.add(m.group(0))
        for rx in ID_RES:
            ids.update(m.group(0) for m in rx.finditer(leaf))
        cleaned = DATE_RE.sub(" ", leaf)
        for tok in NUM_RE.findall(cleaned):
            nums.add(tok)
            try:
                nums |= _num_variants(float(tok.replace(",", "")))
            except ValueError:
                pass
    return nums, ids


def check(text: str, facts) -> dict:
    """返回 {ok, bad_numbers, bad_ids}——ok=False 即白名单违规。"""
    nums, ids = allowed_values(facts)
    bad_numbers: list[str] = []
    bad_ids: list[str] = []
    for tok in NUM_RE.findall(DATE_RE.sub(" ", text)):
        if tok not in nums and tok.replace(",", "") not in nums:
            bad_numbers.append(tok)
    for rx in ID_RES:
        for m in rx.finditer(text):
            if m.group(0) not in ids:
                bad_ids.append(m.group(0))
    return {"ok": not bad_numbers and not bad_ids,
            "bad_numbers": sorted(set(bad_numbers)),
            "bad_ids": sorted(set(bad_ids))}
