"""Read recent messages from a WeChat chat."""
from __future__ import annotations

import asyncio

from .base import BaseOperation, OperationContext, OperationResult, OperationStatus
from .registry import register_operation
from ._helpers import open_chat, sleep_ms, estimate_chat_region, ocr_extract_text


@register_operation("read_messages")
class ReadMessagesOperation(BaseOperation):
    description = "Read recent messages from a chat"
    requires_confirmation = False

    async def execute(self, ctx: OperationContext, params: dict) -> OperationResult:
        chat = params.get("chat") or params.get("to")
        limit = int(params.get("limit", 20))
        if not chat:
            return OperationResult(
                status=OperationStatus.FAILED,
                message="Missing parameter: chat/to",
            )

        ok, msg = await open_chat(ctx, chat)
        if not ok:
            return OperationResult(status=OperationStatus.FAILED, message=msg)

        await sleep_ms(ctx, 500)

        region = await estimate_chat_region(ctx)
        if region is None:
            return OperationResult(
                status=OperationStatus.FAILED,
                message="Could not estimate chat message region",
            )

        screenshot = await asyncio.to_thread(ctx.controller.screenshot, region)
        texts = await ocr_extract_text(screenshot, ctx)

        # Sort by vertical position (top -> bottom) to give messages in chronological order
        texts.sort(key=lambda item: item["center_y"])

        messages = []
        for item in texts[-limit:]:
            messages.append({
                "content": item["text"],
                "confidence": item["confidence"],
            })

        return OperationResult(
            status=OperationStatus.SUCCESS,
            data={
                "chat": chat,
                "messages": messages,
                "count": len(messages),
            },
            message=f"Read {len(messages)} messages from '{chat}'",
        )
