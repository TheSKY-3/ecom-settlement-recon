"""P3 真模型冒烟（手动跑，不进 pytest；需要环境变量 DEEPSEEK_API_KEY）。

用法：.venv/Scripts/python.exe scripts/agent_smoke.py
输出打印到终端；每次调用照常写 output/agent/trace.jsonl 留痕。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.agent import attribute, ask, llm  # noqa: E402


def show(title: str, out: dict) -> None:
    print(f"\n=== {title} ===")
    print(f"[来源] {out['source']}  [事实单指纹] {out['facts_sha256']}")
    print(f"[引用] {', '.join(out['refs']) or '—'}")
    print(f"[答案] {out['answer']}")


def main() -> None:
    if not llm.available():
        print("未设置 DEEPSEEK_API_KEY，无法冒烟。")
        sys.exit(1)

    # ① 归因：从引擎产物里取一条真实发现（优先非孤儿账单，事实单更丰满）
    findings = json.loads(
        (ROOT / "output" / "engine" / "findings.json").read_text(encoding="utf-8")
    )["findings"]
    target = next(f for f in findings if f["variant"] != "孤儿账单")
    show(f"attribute({target['finding_id']}：{target['variant']})",
         attribute.attribute(target["finding_id"]))

    # ② 查账：统计类（模板直答，不花模型调用）
    show('ask("引擎成绩怎么样？")', ask.ask("引擎成绩怎么样？"))

    # ③ 护栏实战：诱导模型说事实单之外的数字
    show('ask("金额最大的那笔账单是多少？")', ask.ask("金额最大的那笔账单是多少？"))


if __name__ == "__main__":
    main()
