"""P2 引擎入口：装载 → 分类 → 验证 → 判分 → 写产物 + 成绩单。
用法：.venv/Scripts/python.exe scripts/run_engine.py
产物：output/engine/{findings.json,findings.csv,score.json} + docs/reports/p2-engine-report.md
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evals.score import score                        # noqa: E402
from src.engine.audit import AuditChain, sha256_of   # noqa: E402
from src.engine.classifier import classify           # noqa: E402
from src.engine.matcher import load_world            # noqa: E402
from src.engine.verifier import verify               # noqa: E402

FINDING_COLUMNS = ["finding_id", "order_id", "diff_type", "variant", "target_side",
                   "confidence", "description", "amount", "verified"]


def _write_report(result: dict, audit: dict, report_path: Path) -> None:
    lines = [
        "# P2 引擎成绩单（无 AI 全量判卷）",
        "",
        f"> 运行 `{result['run_id']}` · 判分口径：injection-spec-v1（检出 = 命中「订单号+类型」）· "
        f"审计链哈希 `{audit['chain_hash'][:12]}…`（输入指纹与步骤明细见 `output/engine/findings.json`）。",
        "",
        "| 指标 | 数值 |", "|---|---|",
        f"| 标准答案 | {result['gt_total']} |",
        f"| 引擎发现 | {result['finding_total']} |",
        f"| 检出 TP | {result['tp']} |",
        f"| 漏检 FN | {result['fn']} |",
        (f"| 误报 FP 合计 | {result['fp']}（命中 P0 自然差异口径 {result['fp_natural']}，"
         f"其他 {result['fp_other']}） |"),
        f"| 检出率 recall | {result['recall']} |",
        f"| 精确率 precision（对 FP-其他口径） | {result['precision_other']} |",
        (f"| 金额一致性（考卷 v1.2） | {result['amount_consistency']['match']}"
         f"/{result['amount_consistency']['checked']} |" if result.get("amount_consistency") else ""),
        "",
        "| 差异类型 | 标准答案 | 检出 | 漏检 | 误报 | 检出率 |", "|---|---|---|---|---|---|",
    ]
    for dtype, m in result["by_type"].items():
        gt_n = m["tp"] + m["fn"]
        lines.append(f"| {dtype} | {gt_n} | {m['tp']} | {m['fn']} | {m['fp']} | {m['recall']} |")
    lines += [
        "",
        "说明：FP-自然 = 引擎如实报出的 P0 盘点在册自然差异（这批数据自带的错，测试集未给标准答案，",
        "按口径单独统计，不计为引擎误报）；FP-其他 才是真正的误报。金额期望与造数共用同一规则卡实现",
        "（`src/synth/bills.py`），容差 ±0.005 BRL。",
        "",
    ]
    report_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="对账引擎全量运行 + 判分")
    ap.add_argument("--synthetic-dir", default=str(ROOT / "data" / "synthetic"))
    ap.add_argument("--db", default=str(ROOT / "data" / "olist.db"))
    ap.add_argument("--out", default=str(ROOT / "output" / "engine"))
    ap.add_argument("--report", default=str(ROOT / "docs" / "reports" / "p2-engine-report.md"))
    args = ap.parse_args()
    out, report_path = Path(args.out), Path(args.report)
    out.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    chain = AuditChain(run_id=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    world = load_world(Path(args.synthetic_dir), Path(args.db))
    chain.add_step("load_world",
                   inputs=[{"name": k, **v} for k, v in world.sources.items()]
                          + [{"name": "olist.db", "path": str(args.db),
                              "sha256": sha256_of(Path(args.db)), "rows": len(world.orders)}],
                   outputs=[{"name": "orders", "rows": len(world.orders)},
                            {"name": "natural_ids", "rows": len(world.natural_ids)}])
    findings = classify(world)
    chain.add_step("classify", params={"rules": "2026-09-26-p2-engine-design.md §1"},
                   outputs=[{"name": "findings", "rows": len(findings)}])
    verify(world, findings)
    chain.add_step("verify",
                   outputs=[{"name": "verified_true",
                             "count": sum(1 for f in findings if f["verified"])}])

    with open(Path(args.synthetic_dir) / "dirty" / "ground_truth.csv",
              newline="", encoding="utf-8") as f:
        gt_rows = list(csv.DictReader(f))
    result = score(gt_rows, findings, world.natural_ids)
    result["run_id"] = chain.run_id
    chain.add_step("score", outputs=[{"name": "score.json"}])
    audit = chain.to_dict()

    (out / "findings.json").write_text(
        json.dumps({"audit": audit, "findings": findings}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    with open(out / "findings.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FINDING_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows([{**x, "verified": int(x["verified"])} for x in findings])
    (out / "score.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    _write_report(result, audit, report_path)
    print(json.dumps({k: result[k] for k in
                      ("gt_total", "finding_total", "tp", "fn", "fp",
                       "fp_natural", "fp_other", "recall", "precision_other")},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
