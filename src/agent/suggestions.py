"""预设提问与“下一步”建议（D016）：全部由规则生成，零模型调用。

约束：
- 每条建议都绑定真实工具和参数（tools 字段），测试会离线执行一遍，保证“点了一定答得出”；
- 动态建议只从本轮事实里取数（不猜、不算），事实里没有的数字不写进建议；
- 顺序固定，不随机：同一事实永远给同一批建议。
"""
from __future__ import annotations

PRESETS: list[dict] = [
    {"text": "这批一共多少条差异？涉案金额多少？",
     "tools": [{"name": "get_overview", "args": {}}]},
    {"text": "这批评测涉及几张表，各有多少行？",
     "tools": [{"name": "get_data_inventory", "args": {}}]},
    {"text": "六类差异分别有多少条？哪类涉及金额最大？",
     "tools": [{"name": "get_type_stats", "args": {}}]},
    {"text": "单边账有几条？举两个例子。",
     "tools": [{"name": "get_type_stats", "args": {}},
               {"name": "search_diffs", "args": {"source": "gt", "diff_type": "单边账",
                                                 "limit": 2}}]},
    {"text": "涉案金额最大的 5 笔差异是哪些？",
     "tools": [{"name": "search_diffs", "args": {"source": "gt", "sort": "amount_desc",
                                                 "limit": 5}}]},
    {"text": "引擎召回率和误报是多少？",
     "tools": [{"name": "get_engine_score", "args": {}}]},
    {"text": "哪类差异的自然差异最多？",
     "tools": [{"name": "get_type_stats", "args": {}}]},
    {"text": "把单边账导成 Excel 对照表。",
     "tools": [{"name": "export_diffs", "args": {"source": "both",
                                                 "diff_type": "单边账"}}]},
    {"text": "GT000001 是什么问题？",
     "tools": [{"name": "get_diff", "args": {"ref": "GT000001"}}]},
]


def _add(out: list[dict], text: str, name: str, args: dict | None = None) -> None:
    if any(item["text"] == text for item in out):
        return
    out.append({"text": text, "tools": [{"name": name, "args": args or {}}]})


def build_suggestions(facts: list[dict], limit: int = 3) -> list[dict]:
    """按“刚才查到了什么”给下一步：只依赖事实，不依赖模型。"""
    overview = next((f for f in facts if f.get("kind") == "overview"), {})
    type_stats = next((f for f in reversed(facts) if f.get("kind") == "type_stats"), None)
    exported = next((f for f in reversed(facts) if f.get("kind") == "export"), None)
    engine = (overview.get("engine") or {}) if isinstance(overview, dict) else {}
    out: list[dict] = []

    if exported:
        _add(out, "看看这批里的自然差异样例", "search_diffs",
             {"source": "engine", "natural_only": True, "limit": 3})
        _add(out, "换一类再导一份：金额不符", "export_diffs",
             {"source": "both", "diff_type": "金额不符"})
        _add(out, "这批一共几张表、各多少行？", "get_data_inventory")
        return out[:limit]

    if type_stats:
        # by_type 既可能是 {类型: 统计}，也可能是工具返回的 [{diff_type: ...}, ...]
        raw = type_stats.get("by_type") or {}
        if isinstance(raw, dict):
            pairs = list(raw.items())
        else:
            pairs = [(stat.get("diff_type"), stat) for stat in raw
                     if isinstance(stat, dict)]
        worst_type, worst_n = None, 0
        for name, stat in pairs:
            if not name or not isinstance(stat, dict):
                continue
            n = int(stat.get("fp_natural") or 0)
            if n > worst_n:
                worst_type, worst_n = name, n
        if worst_type:
            _add(out, f"看{worst_type}的 {worst_n} 条自然差异样例", "search_diffs",
                 {"source": "engine", "diff_type": worst_type,
                  "natural_only": True, "limit": 3})
        _add(out, "把单边账导成 Excel 对照表", "export_diffs",
             {"source": "both", "diff_type": "单边账"})
        _add(out, "引擎召回率和误报是多少？", "get_engine_score")
        _add(out, "这批一共几张表、各多少行？", "get_data_inventory")
        return out[:limit]

    natural = int(engine.get("fp_natural") or 0)
    if natural:
        _add(out, f"引擎报的 {natural} 条自然差异，举三个例子", "search_diffs",
             {"source": "engine", "natural_only": True, "limit": 3})
    _add(out, "把单边账导成 Excel 对照表", "export_diffs",
         {"source": "both", "diff_type": "单边账"})
    _add(out, "这批一共几张表、各多少行？", "get_data_inventory")
    if len(out) < limit:
        _add(out, "单边账举两个例子", "search_diffs",
             {"source": "gt", "diff_type": "单边账", "limit": 2})
    return out[:limit]


def preset_texts() -> list[str]:
    return [item["text"] for item in PRESETS]
