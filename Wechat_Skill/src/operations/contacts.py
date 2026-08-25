"""Contact and chat session operations.

Operations:
- Search for a contact and open the chat
- List recent chat sessions (via screenshot + OCR of the session list)
- Get contact info visible in the chat header

Parameters vary by sub-operation.
"""
from __future__ import annotations

from .base import BaseOperation, OperationContext, OperationResult, OperationStatus
from .registry import register_operation


@register_operation("open_chat")
class OpenChatOperation(BaseOperation):
    description = "Search for a contact/group and open the chat window"

    async def execute(self, ctx: OperationContext, params: dict) -> OperationResult:
        """TODO: implement open chat workflow.

        This is a shared building block used by send_message, read_messages, etc.

        Steps:
        1. ctx.controller.activate_window()
        2. ctx.controller.press_keys('Ctrl', 'f')
        3. ctx.controller._delay()
        4. ctx.controller.type_text(params['name'])
        5. ctx.controller._delay()
        6. ctx.controller.press_keys('Enter')

        Consider extracting this into a shared utility function in operations/base.py
        or a helper module that other operations can call.
        """
        raise NotImplementedError("Implement: activate -> search -> open chat")


@register_operation("list_sessions")
class ListSessionsOperation(BaseOperation):
    description = "List recent chat sessions from the sidebar"

    async def execute(self, ctx: OperationContext, params: dict) -> OperationResult:
        """TODO: implement list sessions.

        Steps:
        1. ctx.controller.activate_window()
        2. Screenshot the left sidebar (session list area)
        3. OCR to extract session names
        4. Return list of { "name": "...", "preview": "..." }

        Notes:
        - Session list is in the left panel; need to crop screenshot to that region
        - May need to scroll to see all sessions
        """
        raise NotImplementedError("Implement: screenshot sidebar -> OCR -> list sessions")
