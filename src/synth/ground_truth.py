"""标准答案（ground truth）：埋雷时记录每颗雷的位置、类型、证据描述。

这是评测的"分母"——检出率/误报率/归因准确率都拿它当基准。格式冻结后
评测器（evals/）判分只认 (order_id, diff_type) 两列，其余列不许随意改动。

考卷 v1.2（2026-11-02）：新增第 7 列 amount（涉案金额，两位小数字符串）。
注入器在埋雷现场记录金额（删掉的行、改前改后的差值、版本差值），引擎侧
按同一账本独立复算，判分时逐条对账（见 evals/score.py 的 amount_consistency）。
该列为加列升级：既有六列与既有考卷逐行一致，历史成绩不受影响。
"""

import csv
from pathlib import Path

COLUMNS = ["gt_id", "order_id", "diff_type", "variant", "target_side",
           "description", "amount"]

DIFF_TYPES = {"单边账", "金额不符", "状态不一致", "退款遗漏", "重复结算", "版本差异"}


def make_row(order_id: str, diff_type: str, variant: str, target_side: str,
             description: str, seq: int, amount: float | None = None) -> dict:
    if diff_type not in DIFF_TYPES:
        raise ValueError(f"非法差异类型: {diff_type}（必须是 {sorted(DIFF_TYPES)} 之一）")
    if amount is not None and amount < 0:
        raise ValueError(f"涉案金额不能为负: {amount}（{order_id} {variant}）")
    return {
        "gt_id": f"GT{seq:06d}",
        "order_id": order_id,
        "diff_type": diff_type,
        "variant": variant,
        "target_side": target_side,
        "description": description,
        "amount": None if amount is None else f"{round(amount, 2):.2f}",
    }


def write(rows: list[dict], path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def read(path: Path) -> list[dict]:
    with Path(path).open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))
