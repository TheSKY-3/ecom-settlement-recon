#!/usr/bin/env python3
"""生成冻结评测集：data/olist.db → data/synthetic/{clean,dirty} + ground_truth.csv。

用法（项目根目录）：
    .venv/Scripts/python.exe scripts/build_synthetic.py [输出目录]
前置：先跑 scripts/build_db.py 生成 data/olist.db。
自校验失败会直接报错退出，绝不带病输出。
"""

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.synth.build_dataset import build  # noqa: E402


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "synthetic"
    db = ROOT / "data" / "olist.db"
    if not db.exists():
        sys.exit(f"[FAIL] {db} 不存在，先运行 scripts/build_db.py")
    conn = sqlite3.connect(db)
    summary = build(conn, out)
    conn.close()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"[OK] 评测集已写入 {out}（同种子重跑结果逐字节一致）")


if __name__ == "__main__":
    main()
