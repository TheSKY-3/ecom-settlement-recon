"""P4 BenchRec 跨域跑分：确定性引擎 vs 官方 ChatGPT 基线，同一判分器同台对比。

用法：.venv/Scripts/python.exe scripts/run_benchrec.py
数据：data/raw/benchrec/（gitignore）；输出打印 + docs/reports/p4-benchrec-report.md
"""
from __future__ import annotations

import csv
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.benchrec import matcher, score                     # noqa: E402

DATA = ROOT / "data" / "raw" / "benchrec"
EVAL = DATA / "BenchRec_cash_v1.0_eval.csv"
SOLUTION = DATA / "BenchRec_cash_v1.0_solution.csv"
CHATGPT = DATA / "MatcherByChatGPT_submission.csv"
REPORT = ROOT / "docs" / "reports" / "p4-benchrec-report.md"


def load_eval() -> tuple[list[dict], list[dict]]:
    b_rows, a_rows = [], []
    with open(EVAL, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("B_id"):
                b_rows.append(row)
            elif row.get("A_id"):
                a_rows.append(row)
    return b_rows, a_rows


def write_submission(pred: dict, path: Path) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["B_id", "targetAllocation"])
        for b_id, keys in pred.items():
            w.writerow([b_id, json.dumps(sorted(keys), ensure_ascii=False)])


def main() -> None:
    t0 = time.time()
    b_rows, a_rows = load_eval()
    truth = score.load_solution(SOLUTION)
    print(f"载入 eval：B {len(b_rows)} / A {len(a_rows)}；真值 {len(truth)} 条", flush=True)

    pred = matcher.match(b_rows, a_rows)
    ours = score.score(pred, truth)
    print(f"确定性引擎匹配完成（{time.time() - t0:.1f}s）", flush=True)

    gpt_pred = score.load_submission(CHATGPT)
    gpt = score.score(gpt_pred, truth)

    out_dir = ROOT / "output" / "benchrec"
    out_dir.mkdir(parents=True, exist_ok=True)
    write_submission(pred, out_dir / "deterministic_submission.csv")

    print(json.dumps({"ours": ours, "chatgpt_baseline": gpt}, ensure_ascii=False, indent=1))
    _write_report(ours, gpt, len(b_rows), len(a_rows), time.time() - t0)


def _write_report(ours: dict, gpt: dict, n_b: int, n_a: int, secs: float) -> None:
    def row(name: str, m: dict) -> str:
        return (f"| {name} | {m['correct']:,} | {m['attempted']:,} | "
                f"{m['precision'] * 100:.2f}% | {m['coverage'] * 100:.1f}% | "
                f"{m['accuracy'] * 100:.2f}% |")

    lines = [
        "# P4 BenchRec 跨域成绩单（确定性引擎 vs 官方 ChatGPT 基线）",
        "",
        f"> 数据：BenchRec cash v1.0 eval（B 交易 {n_b:,} / A 分录 {n_a:,}，CC BY 4.0）；",
        "> 判对口径 = 预测分配集合 ⊆ 真值集合（宁缺勿错，与竞赛一致）；"
        f"本引擎耗时 {secs:.1f}s（纯标准库）。",
        "",
        "| 提交 | 判对 | 匹配决策 | 精度 | 覆盖率 | 总判对率 |",
        "|---|---|---|---|---|---|",
        row("确定性引擎（本项目）", ours),
        row("官方 ChatGPT 基线", gpt),
        "",
        "说明：精度 = 匹配决策中判对的比例（竞赛硬门槛 99.8%）；覆盖率 = 做出匹配决策的 B 交易占比；",
        "总判对率 = 判对 / 全部。双空（真值无匹配且未决策）判对但不计匹配决策。",
        "引擎输出落盘 `output/benchrec/deterministic_submission.csv`（gitignore）。",
        "",
        f"运行：{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%MZ')}",
    ]
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"报告已写 {REPORT}")


if __name__ == "__main__":
    main()
