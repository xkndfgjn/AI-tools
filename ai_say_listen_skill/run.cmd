@echo off
chcp 65001 >nul
cd /d "%~dp0"
python main.py
if errorlevel 1 (
  echo.
  echo 启动失败。若提示缺少依赖，请先运行：python scripts\setup_env.py
  pause
)
