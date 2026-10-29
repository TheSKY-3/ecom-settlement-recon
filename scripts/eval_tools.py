"""跑工具调用评测：离线看工具覆盖度，在线看模型选工具的质量。

用法（Windows PowerShell）：
  .\\.venv\\Scripts\\python.exe scripts\\eval_tools.py            # 离线，无需 key
  .\\.venv\\Scripts\\python.exe scripts\\eval_tools.py --live      # 需 DEEPSEEK_API_KEY
  .\\.venv\\Scripts\\python.exe scripts\\eval_tools.py --live --limit 8

退出码：0 = 全部通过；1 = 有失败（便于将来接 CI）。
离线依赖 output/engine/ 与 data/synthetic/（均已生成才可跑，产物 gitignore）。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals import tool_use  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="工具调用评测")
    ap.add_argument("--live", action="store_true", help="用真模型跑（需要 key）")
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 个用例")
    ap.add_argument("--out", default="", help="把完整结果写成 JSON 的路径")
    args = ap.parse_args(argv)

    cases = tool_use.CASES[:args.limit] if args.limit else tool_use.CASES
    try:
        result = (tool_use.run_live(cases) if args.live
                  else tool_use.run_offline(cases))
    except FileNotFoundError as e:
        print(f"数据未就绪：{e}", file=sys.stderr)
        return 2

    print(tool_use.summarize(result))
    if args.out:
        tool_use.write_result(result, args.out)
        print(f"完整结果：{args.out}")

    if result.get("skipped"):
        return 0
    failed = ([i["id"] for i in result["items"] if not i["ok"]]
              if result["mode"] == "offline"
              else [i["id"] for i in result["items"] if not i["facts_ok"]])
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
