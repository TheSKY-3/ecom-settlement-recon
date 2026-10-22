"""工作台服务入口：python -m src.workbench.serve [--host 127.0.0.1] [--port 8770] [--open-browser]"""
from __future__ import annotations

import argparse
import socket
import threading
import webbrowser

import uvicorn

from src.workbench.app import app


def pick_port(start: int, stop: int = 8779) -> int:
    for port in range(start, stop + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError(f"{start}~{stop} 端口都被占用")


def main() -> None:
    ap = argparse.ArgumentParser(description="对账工作台本地服务")
    ap.add_argument("--host", default="127.0.0.1",
                    help="监听地址；容器里传 0.0.0.0，默认只监听本机回环")
    ap.add_argument("--port", type=int, default=8770)
    ap.add_argument("--open-browser", action="store_true")
    args = ap.parse_args()
    port = pick_port(args.port)
    url = f"http://127.0.0.1:{port}"
    if args.open_browser:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    print(f"对账工作台：{url}（关闭本窗口即停止服务）")
    uvicorn.run(app, host=args.host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
