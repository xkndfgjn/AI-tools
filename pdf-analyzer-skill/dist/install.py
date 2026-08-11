"""插件安装脚本：创建虚拟环境并安装依赖。

被 plugin.json 的 preload 字段调用：
    python install.py

职责：
    1. 在 runtime/mcp_server 下创建 .venv 虚拟环境
    2. 安装 requirements.txt 中的依赖（mcp、PyMuPDF）
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
MCP_SERVER_DIR = ROOT_DIR / "runtime" / "mcp_server"
VENV_DIR = MCP_SERVER_DIR / ".venv"
REQUIREMENTS = MCP_SERVER_DIR / "requirements.txt"


def _venv_python() -> Path:
    if sys.platform == "win32":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def main() -> int:
    print(f"[install] 项目目录：{ROOT_DIR}")

    if not REQUIREMENTS.exists():
        print(f"[install] 错误：未找到 {REQUIREMENTS}", file=sys.stderr)
        return 1

    if not (VENV_DIR / "Scripts" / "python.exe").exists() and not (VENV_DIR / "bin" / "python").exists():
        print("[install] 创建虚拟环境...")
        subprocess.run([sys.executable, "-m", "venv", str(VENV_DIR)], check=True)

    py = _venv_python()
    print(f"[install] 虚拟环境解释器：{py}")

    print("[install] 安装依赖...")
    subprocess.run(
        [str(py), "-m", "pip", "install", "--upgrade", "pip"],
        check=True,
    )
    subprocess.run(
        [str(py), "-m", "pip", "install", "-r", str(REQUIREMENTS)],
        check=True,
    )

    print("[install] 安装完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
