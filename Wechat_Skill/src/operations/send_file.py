"""Send a file or image to a WeChat contact or group."""
from __future__ import annotations

import asyncio
import os

from .base import BaseOperation, OperationContext, OperationResult, OperationStatus
from .registry import register_operation
from ._helpers import open_chat, sleep_ms


@register_operation("send_file")
class SendFileOperation(BaseOperation):
    description = "Send a file or image to a contact or group"
    requires_confirmation = False

    async def execute(self, ctx: OperationContext, params: dict) -> OperationResult:
        to = params.get("to")
        file_path = params.get("file_path")
        if not to:
            return OperationResult(
                status=OperationStatus.FAILED,
                message="Missing parameter: to",
            )
        if not file_path:
            return OperationResult(
                status=OperationStatus.FAILED,
                message="Missing parameter: file_path",
            )
        if not os.path.exists(file_path):
            return OperationResult(
                status=OperationStatus.FAILED,
                message=f"File not found: {file_path}",
            )

        ok, msg = await open_chat(ctx, to)
        if not ok:
            return OperationResult(status=OperationStatus.FAILED, message=msg)

        # WeChat shortcut: Ctrl+Shift+F opens the file picker
        await asyncio.to_thread(ctx.controller.press_keys, "Ctrl", "Shift", "f")
        await sleep_ms(ctx, 800)

        await asyncio.to_thread(ctx.controller.type_text, os.path.abspath(file_path))
        await sleep_ms(ctx, 400)

        # Confirm file selection in the dialog
        await asyncio.to_thread(ctx.controller.press_keys, "Enter")
        await sleep_ms(ctx, 600)

        # Confirm send (some WeChat versions need a second Enter)
        await asyncio.to_thread(ctx.controller.press_keys, "Enter")
        await sleep_ms(ctx, 500)

        return OperationResult(
            status=OperationStatus.SUCCESS,
            data={"to": to, "file_path": file_path},
            message=f"File sent to '{to}'",
        )
