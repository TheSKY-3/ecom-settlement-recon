"""标准答案（ground truth）：埋雷时记录每颗雷的位置、类型、证据描述。

这是评测的"分母"——检出率/误报率/归因准确率都拿它当基准。格式冻结后
评测器（evals/）只认这六列，不许随意加列。
"""

import csv
from pathlib import Path

COLUMNS = ["gt_id", "order_id", "diff_type", "variant", "target_side", "description"]

DIFF_TYPES = {"单边账", "金额不符", "状态不一致", "退款遗漏", "重复结算", "版本差异"}


def make_row(order_id: str, diff_type: str, variant: str, target_side: str,
             description: str, seq: int) -> dict:
    if diff_type not in DIFF_TYPES:
        raise ValueError(f"非法差异类型: {diff_type}（必须是 {sorted(DIFF_TYPES)} 之一）")
    return {
        "gt_id": f"GT{seq:06d}",
        "order_id": order_id,
        "diff_type": diff_type,
        "variant": variant,
        "target_side": target_side,
        "description": description,
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
