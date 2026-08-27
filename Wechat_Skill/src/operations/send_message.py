"""Send text message to a WeChat contact or group."""
from __future__ import annotations

import asyncio

from .base import BaseOperation, OperationContext, OperationResult, OperationStatus
from .registry import register_operation
from ._helpers import open_chat, sleep_ms


@register_operation("send_message")
class SendMessageOperation(BaseOperation):
    description = "Send a text message to a contact or group"
    requires_confirmation = False

    async def execute(self, ctx: OperationContext, params: dict) -> OperationResult:
        to = params.get("to")
        text = params.get("text")
        if not to:
            return OperationResult(
                status=OperationStatus.FAILED,
                message="Missing parameter: to",
            )
        if text is None:
            return OperationResult(
                status=OperationStatus.FAILED,
                message="Missing parameter: text",
            )

        ok, msg = await open_chat(ctx, to)
        if not ok:
            return OperationResult(status=OperationStatus.FAILED, message=msg)

        await asyncio.to_thread(ctx.controller.type_text, str(text))
        await sleep_ms(ctx, 200)
        await asyncio.to_thread(ctx.controller.press_keys, "Enter")
        await sleep_ms(ctx, 500)

        return OperationResult(
            status=OperationStatus.SUCCESS,
            data={"to": to, "text": text},
            message=f"Message sent to '{to}'",
        )
