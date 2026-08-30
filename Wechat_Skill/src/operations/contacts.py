"""Contact and chat session operations."""
from __future__ import annotations

import asyncio
import re
from typing import Iterable, List

from .base import BaseOperation, OperationContext, OperationResult, OperationStatus
from .registry import register_operation
from ._helpers import open_chat, sleep_ms, ocr_extract_text
from ..rpa.finder import FindTarget

_STATIC_LABELS = {
    "微信",
    "通讯录",
    "发现",
    "我",
    "搜索",
    "设置",
    "帮助",
    "收藏",
    "聊天",
    "消息",
}
_TIME_RE = re.compile(
    r"^(?:"
    r"\d{1,2}[:：]\d{2}"
    r"|(?:昨天|今天|前天|明天)\s*\d{1,2}[:：]\d{2}"
    r"|(?:星期|周)[一二三四五六日天]"
    r"|(?:上午|中午|下午|晚上)\s*\d{1,2}[:：]\d{2}"
    r"|\d{4}[/-]\d{1,2}[/-]\d{1,2}(?:\s*\d{1,2}[:：]\d{2})?"
    r")$"
)


def _is_time_like(text: str) -> bool:
    return bool(_TIME_RE.match((text or "").strip()))


def _is_sidebar_label(text: str) -> bool:
    text = (text or "").strip()
    if not text:
        return True
    if text in _STATIC_LABELS:
        return True
    return "聊天记录" in text or "历史记录" in text or "已读" in text


def _x_interval(block: dict) -> tuple[float, float]:
    box = block.get("box") or [[0, 0], [0, 0], [0, 0], [0, 0]]
    xs = [p[0] for p in box]
    return min(xs), max(xs)


def _same_session_group(a: dict, b: dict) -> bool:
    """Group rows in the same session band by vertical proximity.

    In sidebar OCR, the preview line and timestamp usually share the same item
    band but sit at different x positions. So the stable rule is "close in y"
    rather than "overlap in x".
    """
    return abs(a["center_y"] - b["center_y"]) <= max(40, a["height"] * 1.5, b["height"] * 1.5)


def parse_session_entries(items: Iterable[dict]) -> List[dict]:
    """Parse OCR sidebar candidates into name-like session entries.

    WeChat session list is a vertical stack of entries, each usually split into:
    1) name row, 2) preview row, 3) time label. This function groups rows that
    belong to the same sidebar item and keeps the shortest name-like row as the
    session name, discarding static labels, timestamps and preview snippets.
    """
    blocks = []
    for item in items:
        text = (item.get("text") or "").strip()
        if not text:
            continue
        if _is_sidebar_label(text):
            continue
        if len(text) <= 1:
            continue
        blocks.append({**item, "text": text})

    if not blocks:
        return []

    ordered = sorted(blocks, key=lambda b: (b["center_y"], b["center_x"]))
    groups: list[list[dict]] = []
    for block in ordered:
        if not groups:
            groups.append([block])
            continue
        prev = groups[-1]
        if _same_session_group(prev[-1], block):
            prev.append(block)
        else:
            groups.append([block])

    sessions: list[dict] = []
    for group in groups:
        entries = []
        for block in group:
            text = (block.get("text") or "").strip()
            if not text or _is_sidebar_label(text):
                continue
            if _is_time_like(text):
                entries.append({"kind": "time", "text": text, "y": block["center_y"]})
                continue
            entries.append({"kind": "text", "text": text, "y": block["center_y"]})
        if not entries:
            continue
        text_rows = [e for e in entries if e["kind"] == "text"]
        if not text_rows:
            continue
        name_row = min(text_rows, key=lambda e: e["y"])
        preview_candidates = [e for e in text_rows if e["y"] > name_row["y"]]
        preview_row = min(preview_candidates, key=lambda e: e["y"]) if preview_candidates else name_row
        time_value = None
        time_rows = [e for e in entries if e["kind"] == "time"]
        if time_rows:
            nearest = min(time_rows, key=lambda e: abs(e["y"] - name_row["y"]))
            time_value = nearest["text"]
        sessions.append({
            "name": name_row["text"],
            "preview": preview_row["text"],
            "time": time_value,
            "source": "ocr",
            "confidence": 1.0,
        })

    # Deduplicate by name while preserving order.
    deduped: list[dict] = []
    seen = set()
    for session in sessions:
        name = session["name"]
        if name in seen:
            continue
        seen.add(name)
        deduped.append(session)
    return deduped


@register_operation("open_chat")
class OpenChatOperation(BaseOperation):
    description = "Search for a contact/group and open the chat window"

    async def execute(self, ctx: OperationContext, params: dict) -> OperationResult:
        name = params.get("name") or params.get("to") or params.get("chat")
        if not name:
            return OperationResult(
                status=OperationStatus.FAILED,
                message="Missing parameter: name/to/chat",
            )

        ok, msg = await open_chat(ctx, name)
        if not ok:
            return OperationResult(status=OperationStatus.FAILED, message=msg)

        return OperationResult(
            status=OperationStatus.SUCCESS,
            data={"opened": name},
            message=f"Opened chat with '{name}'",
        )


@register_operation("list_sessions")
class ListSessionsOperation(BaseOperation):
    description = "List recent chat sessions from the sidebar"

    async def execute(self, ctx: OperationContext, params: dict) -> OperationResult:
        controller = ctx.controller

        activated = await asyncio.to_thread(controller.activate_window)
        if not activated:
            return OperationResult(
                status=OperationStatus.FAILED,
                message="WeChat window not found or could not be activated",
            )

        await sleep_ms(ctx, 300)
        rect = controller.get_window_rect()
        if rect is None:
            return OperationResult(
                status=OperationStatus.FAILED,
                message="Could not determine WeChat window rect",
            )

        left, top, right, bottom = rect
        width = right - left

        # Qt-rendered WeChat exposes an empty UIA control tree, so the sidebar
        # must be parsed directly from OCR instead of trying any control-based
        # fallback. This keeps the operation stable and avoids dead branches.
        sidebar_right = left + int(width * 0.38)
        region = (left, top, sidebar_right, bottom)
        screenshot = await asyncio.to_thread(controller.screenshot, region)
        texts = await ocr_extract_text(screenshot, ctx)
        sessions = parse_session_entries(texts)

        return OperationResult(
            status=OperationStatus.SUCCESS,
            data={"sessions": sessions, "count": len(sessions)},
            message=f"Found {len(sessions)} sessions",
        )
