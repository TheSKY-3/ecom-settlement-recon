"""构建 exe 启动器：先确保 requirements.txt 已安装（含 pyinstaller），
再跑 .venv/Scripts/python.exe scripts/build_launcher.py。
产物：项目根目录/对账工作台.exe（仅几 MB，只含启动逻辑，不含应用与数据）。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXE = ROOT / "对账工作台.exe"


def main() -> None:
    cmd = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--onefile", "--console", "--name", "对账工作台",
        "--distpath", str(ROOT), "--workpath", str(ROOT / "tmp" / "pyinstaller"),
        "--specpath", str(ROOT / "tmp" / "pyinstaller"),
        str(ROOT / "launcher" / "launcher.py"),
    ]
    subprocess.run(cmd, check=True, cwd=str(ROOT))
    if not EXE.is_file():
        raise SystemExit("构建完成但找不到产物 对账工作台.exe")
    size_mb = EXE.stat().st_size / 1024 / 1024
    print(f"OK: {EXE}（{size_mb:.1f} MB）")


if __name__ == "__main__":
    main()
