"""Read recent messages from a WeChat chat.

Workflow:
1. Activate WeChat window
2. Open the target chat (via search or clicking the session list)
3. Screenshot the message area
4. OCR to extract text messages
5. Return structured message list

Parameters:
    chat (str): contact or group name to read from
    limit (int): max number of messages to return (default 20)
"""
from __future__ import annotations

from .base import BaseOperation, OperationContext, OperationResult, OperationStatus
from .registry import register_operation


@register_operation("read_messages")
class ReadMessagesOperation(BaseOperation):
    description = "Read recent messages from a chat"
    requires_confirmation = False

    async def execute(self, ctx: OperationContext, params: dict) -> OperationResult:
        """TODO: implement read messages workflow.

        Steps:
        1. ctx.controller.activate_window()
        2. Open target chat (search + Enter, same as send_message steps 2-6)
        3. ctx.controller.screenshot() -> capture message area
        4. ctx.finder.find(screenshot, FindTarget(text=...)) -> OCR all text
           OR use easyocr.Reader directly for full-text extraction
        5. Parse OCR results into message list:
           [{ "sender": "...", "content": "...", "time": "..." }, ...]
        6. Return as OperationResult(status=SUCCESS, data={"messages": [...]})

        Notes:
        - WeChat 4.x uses self-drawn UI, so OCR is the primary extraction method
        - May need to scroll up to read more messages (drag operation)
        - Message boundaries are hard to detect via OCR; best-effort parsing
        """
        raise NotImplementedError(
            "Implement: open chat -> screenshot message area -> OCR -> parse messages"
        )
