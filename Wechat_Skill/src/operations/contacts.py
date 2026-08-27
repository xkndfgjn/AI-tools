"""Contact and chat session operations."""
from __future__ import annotations

import asyncio

from .base import BaseOperation, OperationContext, OperationResult, OperationStatus
from .registry import register_operation
from ._helpers import open_chat, sleep_ms, ocr_extract_text
from ..rpa.finder import FindTarget


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

        # 1. Try control tree first: common session-list control types
        sessions = []
        for control_type in ("ListItemControl", "DataItemControl"):
            infos = await asyncio.to_thread(
                controller.find_controls_info,
                control_type=control_type,
                depth=5,
            )
            for info in infos:
                name = info.get("name", "").strip()
                if name:
                    sessions.append({"name": name, "source": "control_tree"})
            if sessions:
                break

        # 2. OCR fallback on the left sidebar
        if not sessions:
            sidebar_right = left + int(width * 0.38)
            region = (left, top, sidebar_right, bottom)
            screenshot = await asyncio.to_thread(controller.screenshot, region)
            texts = await ocr_extract_text(screenshot, ctx)
            static_labels = {"微信", "搜索", "通讯录", "发现", "我", "文件传输助手"}
            seen = set()
            for item in texts:
                name = item["text"].strip()
                if not name or name in static_labels or name in seen:
                    continue
                seen.add(name)
                sessions.append({"name": name, "confidence": item["confidence"], "source": "ocr"})

        return OperationResult(
            status=OperationStatus.SUCCESS,
            data={"sessions": sessions, "count": len(sessions)},
            message=f"Found {len(sessions)} sessions",
        )
