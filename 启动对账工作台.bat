@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo [对账工作台] 找不到 .venv\Scripts\python.exe，请先在项目根目录创建虚拟环境。
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m src.workbench.serve --open-browser
