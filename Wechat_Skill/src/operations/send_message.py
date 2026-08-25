"""Send text message to a WeChat contact or group.

Workflow:
1. Activate WeChat window
2. Ctrl+F to open search, type contact name, Enter to open chat
3. Paste message text, Enter to send

Parameters:
    to (str): contact name or group name (fuzzy matched by WeChat search)
    text (str): message content
"""
from __future__ import annotations

from .base import BaseOperation, OperationContext, OperationResult, OperationStatus
from .registry import register_operation


@register_operation("send_message")
class SendMessageOperation(BaseOperation):
    description = "Send a text message to a contact or group"
    requires_confirmation = False

    async def execute(self, ctx: OperationContext, params: dict) -> OperationResult:
        """TODO: implement send message workflow.

        Steps:
        1. ctx.controller.activate_window()
        2. ctx.controller.press_keys('Ctrl', 'f')   # open search
        3. ctx.controller._delay()
        4. ctx.controller.type_text(params['to'])     # type contact name
        5. ctx.controller._delay()
        6. ctx.controller.press_keys('Enter')        # open chat
        7. ctx.controller._delay()
        8. ctx.controller.type_text(params['text'])  # type message
        9. ctx.controller.press_keys('Enter')         # send

        Error handling:
        - If search returns no results -> return FAILED with message
        - Use ctx.finder to verify search results appeared (optional)
        """
        raise NotImplementedError(
            "Implement: activate -> search contact -> open chat -> paste message -> send"
        )
