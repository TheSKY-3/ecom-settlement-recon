"""对账工作台启动器：只负责拉起 venv 的 Python 服务并打开浏览器。
应用代码与数据不打包进 exe——换机器/改代码无需重新打包。"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def project_root() -> Path:
    if getattr(sys, "frozen", False):          # PyInstaller 打包后，exe 所在目录即项目根
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def main() -> None:
    root = project_root()
    python = root / ".venv" / "Scripts" / "python.exe"
    if not python.is_file():
        print(f"[对账工作台] 找不到 {python}")
        print("请把本 exe 放在项目根目录，或先创建虚拟环境并安装 requirements.txt。")
        input("按回车退出……")
        raise SystemExit(1)
    env = {**os.environ, "PYTHONUTF8": "1"}
    subprocess.Popen(
        [str(python), "-m", "src.workbench.serve", "--open-browser"],
        cwd=str(root), env=env,
        creationflags=subprocess.CREATE_NEW_CONSOLE,   # 服务在独立控制台窗口，关窗即停
    )


if __name__ == "__main__":
    main()
