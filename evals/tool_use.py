"""D014 工具调用评测：先写"要答的问题"，再看工具集够不够答。

为什么要这个：D011 的 `evals/score.py` 只评引擎准不准，D013 的对话只有零散
单元测试，没有任何指标能回答"多给几个工具之后是不是真的变强了"。

两种模式：
- 离线（默认，不需要 key）：把用例里的**期望工具序列**直接交给 `ChatTools`
  执行，再检查累积的事实能不能满足该问题的断言。它衡量的是*工具集覆盖度*，
  不是模型能力 —— 用例失败即"这类问题现在的工具答不了"。
- 在线（需要 DEEPSEEK_API_KEY）：让真模型跑同一批问题，量四件事：首次工具
  是否命中、期望工具是否都被用到、平均模型往返次数、是走模型还是确定性降级。
  它衡量的是*工具选择质量*，模型换版本、工具描述改动都会体现在这里。

用例里的数字来自冻结评测集（1,750 条标准答案 / 2,325 条引擎发现，见
docs/reports/），改数据集后要同步更新断言 —— 这是有意的：数字变了应当报警。
"""
from __future__ import annotations

import json
import os
from typing import Callable

CASES: list[dict] = []


def case(case_id: str, question: str, steps: list[tuple[str, dict]],
         check: Callable[[list[dict], "ToolExecutor"], tuple[bool, str]]) -> None:
    CASES.append({"id": case_id, "question": question,
                  "steps": steps, "check": check})


# ---- 事实读取小工具 -------------------------------------------------------

def _find(kind: str, facts: list[dict]) -> dict:
    for f in reversed(facts):
        if isinstance(f, dict) and f.get("kind") == kind:
            return f
    return {}


def _rows(facts: list[dict]) -> list[dict]:
    return list(_find("diffs", facts).get("rows") or [])


def _total(facts: list[dict]) -> int:
    return int(_find("diffs", facts).get("total") or 0)


def _type_stat(facts: list[dict], diff_type: str) -> dict:
    for item in _find("type_stats", facts).get("by_type") or []:
        if item.get("diff_type") == diff_type:
            return item
    return {}


def _diffs_totals(facts: list[dict]) -> list:
    return [d.get("total") for d in facts
            if isinstance(d, dict) and d.get("kind") == "diffs"]


def _score(facts: list[dict]) -> dict:
    return _find("engine", facts).get("score") or {}


def _side_total(facts: list[dict], ledger: str, which: str = "gt") -> int:
    by_side = _find("overview", facts).get("gt", {}).get("by_side") or {}
    return int(by_side.get(ledger) or 0)


def _ok(condition: bool, note: str) -> tuple[bool, str]:
    return bool(condition), note


# ---- 用例集 --------------------------------------------------------------
# 覆盖：概览 / 单类计数 / 样例 / 双来源对照 / 按类型聚合（精确率、自然差异）/
# 置信度与复核过滤 / 自然差异样例 / 按账本 / 关键词 / 单条 GT 与 F / 订单 /
# 不存在编号 / 多步计划（>4 步，验证轮次预算）。
# ---------------------------------------------------------------------------

case("overview_total", "这批一共多少条差异？",
     [("get_overview", {})],
     lambda f, ex: _ok(
         _find("overview", f).get("gt", {}).get("total") == 1750
         and len(_find("overview", f).get("gt", {}).get("by_type") or {}) == 6,
         "概览给出 1750 条与六类分布"))


case("type_count", "单边账一共有多少条？",
     [("search_diffs", {"source": "gt", "diff_type": "单边账", "limit": 1})],
     lambda f, ex: _ok(
         _total(f) == 700 or _type_stat(f, "单边账").get("gt") == 700,
         f"单边账 total={_total(f)}/gt={_type_stat(f, '单边账').get('gt')}"))


case("type_samples", "重复结算举两个例子。",
     [("search_diffs", {"source": "gt", "diff_type": "重复结算", "limit": 2})],
     lambda f, ex: _ok(
         _total(f) == 100 and len(_rows(f)) == 2
         and all(r.get("diff_type") == "重复结算" for r in _rows(f)),
         f"重复结算 total={_total(f)} 返回 {len(_rows(f))} 条"))


case("both_sources_count", "重复结算标准答案多少条、引擎报了多少条？",
     [("search_diffs", {"source": "gt", "diff_type": "重复结算", "limit": 1}),
      ("search_diffs", {"source": "engine", "diff_type": "重复结算", "limit": 1})],
     lambda f, ex: _ok(
         _diffs_totals(f) == [100, 100]
         or (_type_stat(f, "重复结算").get("gt") == 100
             and _type_stat(f, "重复结算").get("findings") == 100),
         f"两个来源 total={_diffs_totals(f)}；"
         f"统计={_type_stat(f, '重复结算')}"))


case("type_stats", "每一类差异的标准答案数、引擎发现数和精确率分别是多少？",
     [("get_type_stats", {})],
     lambda f, ex: _ok(
         len(_find("type_stats", f).get("by_type") or []) == 6
         and _type_stat(f, "金额不符").get("gt") == 500
         and _type_stat(f, "金额不符").get("findings") == 1074
         and _type_stat(f, "金额不符").get("fp") == 574
         and _type_stat(f, "金额不符").get("precision") == 0.4655
         and _type_stat(f, "金额不符").get("precision_other") == 1.0,
         f"金额不符统计={_type_stat(f, '金额不符')}"))


case("worst_fp_type", "哪一类差异误报最多，这些误报是什么性质？",
     [("get_type_stats", {})],
     lambda f, ex: _ok(
         max(_find("type_stats", f).get("by_type") or [],
             key=lambda i: i.get("fp") or 0).get("diff_type") == "金额不符"
         and _type_stat(f, "金额不符").get("fp_natural") == 574,
         f"误报最多={_type_stat(f, '金额不符')}"))


case("natural_total", "误报里有多少条是自然差异、多少条是引擎真错？",
     [("get_type_stats", {})],
     lambda f, ex: _ok(
         (_find("type_stats", f).get("totals") or {}).get("fp_natural") == 575
         and (_find("type_stats", f).get("totals") or {}).get("fp_other") == 0
         and (_find("type_stats", f).get("totals") or {}).get("precision") == 0.7527
         and (_find("type_stats", f).get("totals") or {}).get("precision_other") == 1.0
         or (_score(f).get("fp_natural") == 575
             and _score(f).get("fp_other") == 0
             and _score(f).get("precision_other") == 1.0),
         f"totals={_find('type_stats', f).get('totals')}，score={_score(f)}"))


case("natural_samples", "列三条自然差异样例。",
     [("search_diffs", {"source": "engine", "natural_only": True, "limit": 3})],
     lambda f, ex: _ok(
         _total(f) == 575 and len(_rows(f)) == 3
         and all(r.get("diff_type") == "金额不符" for r in _rows(f)),
         f"自然差异 total={_total(f)}，返回 {len(_rows(f))} 条"))


case("natural_by_type", "自然差异里金额不符有几条？",
     [("search_diffs", {"source": "engine", "natural_only": True,
                        "diff_type": "金额不符", "limit": 1})],
     lambda f, ex: _ok(
         _total(f) == 574 or _type_stat(f, "金额不符").get("fp_natural") == 574,
         f"金额不符自然差异 total={_total(f)}，"
         f"统计={_type_stat(f, '金额不符').get('fp_natural')}"))


case("confidence_high", "只看置信度 0.95 及以上的引擎发现，有多少条？",
     [("search_diffs", {"source": "engine", "min_confidence": 0.95, "limit": 1})],
     lambda f, ex: _ok(_total(f) == 1751, f"高置信 total={_total(f)}"))


case("confidence_low", "置信度正好 0.9 的引擎发现有多少条？",
     [("search_diffs", {"source": "engine", "min_confidence": 0.9,
                        "max_confidence": 0.9, "limit": 1})],
     lambda f, ex: _ok(_total(f) == 574, f"0.9 置信 total={_total(f)}"))


case("verified_only", "只看复核通过的引擎发现有多少条？",
     [("search_diffs", {"source": "engine", "verified": True, "limit": 1})],
     lambda f, ex: _ok(_total(f) == 2325, f"已复核 total={_total(f)}"))


case("diff_by_id", "F000001 是哪一类差异？",
     [("get_diff", {"ref": "F000001"})],
     lambda f, ex: _ok(
         (_find("finding", f).get("finding") or {}).get("diff_type")
         in {"单边账", "金额不符", "状态不一致", "退款遗漏", "重复结算", "版本差异"},
         f"F000001 差异={(_find('finding', f).get('finding') or {}).get('diff_type')}"))


case("gt_ledger", "GT000001 对应哪个订单，账单侧有什么证据？",
     [("get_diff", {"ref": "GT000001"})],
     lambda f, ex: _ok(
         _find("gt", f).get("order_id") == "0032d07457ae9c806c79368d7d9ce96b"
         and _find("gt", f).get("bills") == [],
         f"GT000001 order_id={_find('gt', f).get('order_id')}"))


case("order_multi", "订单 0966b61e30c4a07edbd7523f59b3f3e4 报了几条引擎发现？",
     [("get_order", {"order_id": "0966b61e30c4a07edbd7523f59b3f3e4"})],
     lambda f, ex: _ok(
         len(_find("order", f).get("engine_findings") or []) == 2,
         f"发现数={len(_find('order', f).get('engine_findings') or [])}"))


case("side_gt", "退款账本上的标准答案有几条？",
     [("search_diffs", {"source": "gt", "side": "refunds", "limit": 1})],
     lambda f, ex: _ok(_total(f) == 200 or _side_total(f, "refunds") == 200,
                       f"退款账本 total={_total(f)}/概览={_side_total(f, 'refunds')}"))


case("side_engine", "引擎在支付账本上报了多少条？",
     [("search_diffs", {"source": "engine", "side": "payments", "limit": 1})],
     lambda f, ex: _ok(
         _total(f) == 775
         or ((_find("type_stats", f).get("by_side") or {})
             .get("findings", {}).get("payments")) == 775,
         f"支付账本 total={_total(f)}"))


case("keyword_search", "描述里带“费率”的差异有多少条？",
     [("search_diffs", {"source": "gt", "q": "费率", "limit": 3})],
     lambda f, ex: _ok(_total(f) == 250, f"关键词命中 total={_total(f)}"))


case("engine_score", "引擎整体召回率和精确率是多少？",
     [("get_engine_score", {})],
     lambda f, ex: _ok(
         _find("engine", f).get("score", {}).get("recall") == 1.0
         and _find("engine", f).get("score", {}).get("finding_total") == 2325,
         f"engine score={_find('engine', f).get('score')}"))


case("missing_diff", "GT999999 这条差异的证据是什么？",
     [("get_diff", {"ref": "GT999999"})],
     lambda f, ex: _ok(
         _find("error", f).get("error") == "NOT_FOUND"
         or any(x.get("error") == "NOT_FOUND" for x in f),
         "不存在的编号如实返回 NOT_FOUND"))


case("missing_order", "订单 zzz 有没有差异？",
     [("get_order", {"order_id": "zzz"})],
     lambda f, ex: _ok(
         any(x.get("error") == "NOT_FOUND" for x in f)
         or any(x.get("kind") == "diffs" and x.get("total") == 0
                and not (x.get("rows") or []) for x in f),
         "不存在的订单如实返回 NOT_FOUND 或空结果"))


case("natural_explain", "金额不符精确率为什么低，给两条自然差异例子。",
     [("get_type_stats", {}),
      ("search_diffs", {"source": "engine", "natural_only": True,
                        "diff_type": "金额不符", "limit": 2})],
     lambda f, ex: _ok(
         _type_stat(f, "金额不符").get("precision") == 0.4655
         and len(_rows(f)) >= 2
         and all(r.get("diff_type") == "金额不符" for r in _rows(f)),
         f"统计+样例：precision={_type_stat(f, '金额不符').get('precision')}，"
         f"样例 {len(_rows(f))} 条"))


# 问题只说"四类"，不指定哪四类：任选四类、数字对得上即可，不把合理选择判成错。
_FOUR_TYPES = {700, 500, 200, 150, 100}
case("five_step_plan", "先给按类型统计，再分别看四类差异的样例。",
     [("get_type_stats", {}),
      ("search_diffs", {"source": "gt", "diff_type": "单边账", "limit": 1}),
      ("search_diffs", {"source": "gt", "diff_type": "状态不一致", "limit": 1}),
      ("search_diffs", {"source": "gt", "diff_type": "退款遗漏", "limit": 1}),
      ("search_diffs", {"source": "gt", "diff_type": "版本差异", "limit": 1})],
     lambda f, ex: _ok(
         (lambda totals: len(totals) >= 4 and set(totals[:4]) <= _FOUR_TYPES
          and len({r.get("diff_type") for d in f if d.get("kind") == "diffs"
                   for r in (d.get("rows") or [])}) >= 4)(
             [d.get("total") for d in f
              if isinstance(d, dict) and d.get("kind") == "diffs"]),
         f"四类 total={[d.get('total') for d in f if d.get('kind') == 'diffs']}"))


# ---- 运行器 --------------------------------------------------------------

def run_offline(cases: list[dict] | None = None, executor=None) -> dict:
    """按期望工具序列执行并检查事实；不需要 key，也不碰网络。"""
    from src.agent.chat import ChatTools

    ex = executor or ChatTools()
    items = []
    for c in (cases or CASES):
        facts: list[dict] = []
        error = None
        for tool, args in c["steps"]:
            try:
                out, _line = ex.execute(tool, args)
            except Exception as e:  # 工具崩了也要记成失败，不能让评测中断
                error = f"{type(e).__name__}: {e}"
                break
            facts.append(out)
        if error:
            items.append({"id": c["id"], "ok": False, "detail": error})
            continue
        try:
            ok, note = c["check"](facts, ex)
        except Exception as e:
            ok, note = False, f"check 异常：{type(e).__name__}: {e}"
        items.append({"id": c["id"], "ok": bool(ok), "detail": note})
    passed = sum(1 for i in items if i["ok"])
    return {"mode": "offline", "total": len(items), "passed": passed,
            "coverage": round(passed / len(items), 4) if items else 0.0,
            "failed_ids": [i["id"] for i in items if not i["ok"]],
            "items": items}


def run_live(cases: list[dict] | None = None, engine=None,
             service_factory=None) -> dict:
    """真模型跑同一批问题，量工具选择质量；没有 key 直接返回 skipped。"""
    from src.agent import chat, llm

    if not llm.available():
        return {"mode": "live", "skipped": True,
                "reason": "DEEPSEEK_API_KEY 未设置", "items": []}

    def factory():
        if service_factory is not None:
            return service_factory()
        return chat.ChatService(engine=engine or chat.ChatEngine())

    ex = chat.ChatTools()
    items = []
    for c in (cases or CASES):
        expected = list(dict.fromkeys(tool for tool, _ in c["steps"]))
        service = factory()
        try:
            result = service.turn(None, c["question"])
        except Exception as e:
            items.append({"id": c["id"], "source": "error", "first_hit": False,
                          "covered": False, "facts_ok": False, "rounds": 0,
                          "facts_detail": f"{type(e).__name__}: {e}",
                          "detail": f"{type(e).__name__}: {e}"})
            continue
        used = [s.get("name") for s in result.tool_steps if s.get("kind") == "tool"]
        # 关键：用模型"实际查到的事实"跑该问题的断言，而不是要求它必须走同一颗工具。
        # 同一问题常有等价路径（search_diffs / get_type_stats / get_engine_score），
        # 只认预期工具会把正确答案判成失败。
        try:
            facts_ok, facts_detail = c["check"](result.facts or [], ex)
        except Exception as e:
            facts_ok, facts_detail = False, f"check 异常：{type(e).__name__}: {e}"
        items.append({
            "id": c["id"], "source": result.source,
            "first_hit": bool(used) and used[0] in expected,
            "covered": all(t in used for t in expected),
            "facts_ok": bool(facts_ok),
            "used": used, "expected": expected,
            "rounds": int(result.model_calls or 0),
            "refs": len(result.refs or []),
            "answer_len": len(result.answer or ""),
            "facts_detail": facts_detail,
            "detail": result.reason or "",
        })
    n = len(items)
    passed = sum(1 for i in items if i["facts_ok"])
    return {
        "mode": "live", "total": n, "passed": passed,
        "facts_rate": round(passed / n, 4) if n else 0.0,
        "first_hit_rate": round(sum(1 for i in items if i["first_hit"]) / n, 4) if n else 0.0,
        "coverage_rate": round(sum(1 for i in items if i["covered"]) / n, 4) if n else 0.0,
        "llm_rate": round(sum(1 for i in items if i["source"] == "llm") / n, 4) if n else 0.0,
        "avg_rounds": round(sum(i["rounds"] for i in items) / n, 2) if n else 0.0,
        "failed_ids": [i["id"] for i in items if not i["facts_ok"]],
        "items": items,
    }


def summarize(result: dict) -> str:
    if result.get("skipped"):
        return f"[{result['mode']}] 跳过：{result.get('reason')}"
    if result["mode"] == "offline":
        head = (f"[offline] 工具覆盖 {result['passed']}/{result['total']}"
                f"（{result['coverage'] * 100:.1f}%）")
    else:
        head = (f"[live] 事实可答 {result['passed']}/{result['total']}"
                f"（{result['facts_rate'] * 100:.1f}%） · "
                f"首次命中 {result['first_hit_rate'] * 100:.1f}% · "
                f"期望工具覆盖 {result['coverage_rate'] * 100:.1f}% · "
                f"走模型 {result['llm_rate'] * 100:.1f}% · "
                f"平均往返 {result['avg_rounds']}")
    lines = [head]
    for i in result.get("items") or []:
        mark = "PASS" if i.get("ok", i.get("facts_ok", i.get("covered"))) else "FAIL"
        tail = i.get("facts_detail") or i.get("detail", "")
        if result["mode"] == "live" and i.get("used"):
            tail = f"{tail} [用了 {'/'.join(i['used'])}]"
        lines.append(f"  {mark} {i['id']}: {tail}")
    return "\n".join(lines)


def write_result(result: dict, path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
