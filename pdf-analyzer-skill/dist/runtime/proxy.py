"""Skill → MCP 桥接层

被 skill.json 通过 shell 调用：
    python {{plugin_runtime}}/proxy.py <tool_name> "<json_args>"

职责：
    1. 解析命令行参数（工具名 + JSON 参数字符串）
    2. 通过 MCP stdio 客户端连接本地 MCP 服务器（pdf_engine.py）
    3. 将 Skill 层参数映射为 MCP 工具参数
    4. 调用 MCP 工具并拼接返回结果（纯文本），回传给 Skill/Agent

设计要点：
    - 全程 Agent 不参与 MCP 协议，只看到本脚本输出的纯文本结果
    - 自动使用 mcp_server/.venv 里的 Python 解释器（无论调用本脚本的是哪个 Python）
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent
MCP_SERVER_DIR = ROOT_DIR / "runtime" / "mcp_server"
VENV_PYTHON = MCP_SERVER_DIR / ".venv" / "Scripts" / "python.exe"
SERVER_ENTRY = MCP_SERVER_DIR / "pdf_engine.py"

TOOL_MAP: dict[str, dict[str, Any]] = {
    "pdf_txt": {
        "mcp_tool": "pdf_extract_text",
    },
    "pdf_sum": {
        "mcp_tool": "pdf_summarize",
    },
}


def _ensure_venv_python() -> None:
    """若无 .venv 则先调用 install.py 完成安装，保证后续能连接 MCP 服务器。"""
    if not VENV_PYTHON.exists():
        install_script = ROOT_DIR / "install.py"
        print(f"[proxy] 未找到虚拟环境，正在执行安装脚本：{install_script}", file=sys.stderr)
        subprocess.run(
            [sys.executable, str(install_script)],
            cwd=str(ROOT_DIR),
            check=True,
        )


def _relaunch_in_venv_if_needed() -> None:
    """若当前不是 .venv 解释器，则用 .venv 的解释器重新执行本脚本。

    这样无论外部通过哪种 Python 调用本脚本，都能保证导入 mcp 客户端库。
    """
    current = Path(sys.executable).resolve()
    venv = VENV_PYTHON.resolve()
    if current == venv:
        return

    _ensure_venv_python()
    os.execv(str(venv), [str(venv), str(Path(__file__).resolve()), *sys.argv[1:]])


def _parse_pr(pr: str | None) -> tuple[int, int]:
    """解析 Skill 层的页码范围参数 'pr'，如 '1-3' 或 '3'。返回 (start, end)，从 0 开始。"""
    if not pr:
        return 0, -1
    pr = str(pr).strip()
    if "-" in pr:
        a, _, b = pr.partition("-")
        try:
            start = max(int(a.strip()) - 1, 0)  # Skill 层是 1-based
            end = int(b.strip()) - 1 if b.strip() else -1
        except ValueError:
            return 0, -1
        return start, end
    try:
        idx = int(pr.strip()) - 1
        return max(idx, 0), idx
    except ValueError:
        return 0, -1


def _build_mcp_arguments(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    """把 Skill 层参数转换为 MCP 工具参数。"""
    if tool_name == "pdf_txt":
        mcp_args: dict[str, Any] = {"file_path": args.get("fp", "")}
        pr = args.get("pr")
        if pr:
            start, end = _parse_pr(pr)
            mcp_args["page_start"] = start
            mcp_args["page_end"] = end
        # ocr 参数：当前 MCP 工具为纯文本提取，OCR 属于后续扩展
        return mcp_args

    if tool_name == "pdf_sum":
        mcp_args = {"file_path": args.get("fp", "")}
        length = args.get("len")
        if length is not None:
            try:
                mcp_args["length"] = int(length)
            except (TypeError, ValueError):
                pass
        return mcp_args

    raise ValueError(f"未知工具：{tool_name}")


async def _run_tool(tool_name: str, args: dict[str, Any]) -> str:
    """通过 MCP stdio 客户端调用服务器上的工具，返回拼接后的纯文本。"""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.types import TextContent

    mcp_tool = TOOL_MAP[tool_name]["mcp_tool"]
    mcp_args = _build_mcp_arguments(tool_name, args)

    params = StdioServerParameters(
        command=str(VENV_PYTHON),
        args=[str(SERVER_ENTRY)],
        cwd=str(MCP_SERVER_DIR),
    )

    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.call_tool(mcp_tool, mcp_args)

    texts = [
        c.text
        for c in result.content
        if isinstance(c, TextContent)
    ]
    if result.is_error:
        raise RuntimeError("".join(texts) or f"MCP 工具 {mcp_tool} 执行失败")

    if not texts:
        return "[无返回内容]"
    return "\n".join(texts)


def main() -> int:
    if len(sys.argv) < 2:
        print("用法：python proxy.py <tool_name> [json_args]", file=sys.stderr)
        return 2

    tool_name = sys.argv[1]
    if tool_name not in TOOL_MAP:
        print(f"未知工具：{tool_name}，可用：{', '.join(TOOL_MAP)}", file=sys.stderr)
        return 2

    raw_args = sys.argv[2] if len(sys.argv) > 2 else "{}"
    try:
        args = json.loads(raw_args) if raw_args.strip() else {}
    except json.JSONDecodeError:
        args = {}

    try:
        text = asyncio.run(_run_tool(tool_name, args))
    except Exception as exc:  # noqa: BLE001 - 需要把错误以文本形式返回给 Agent
        print(f"错误：{exc}", file=sys.stderr)
        return 1

    print(text)
    return 0


if __name__ == "__main__":
    _relaunch_in_venv_if_needed()
    raise SystemExit(main())