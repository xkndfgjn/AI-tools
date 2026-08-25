"""Send a file or image to a WeChat contact or group.

Workflow:
1. Activate WeChat window
2. Open target chat (search + Enter)
3. Send file via one of:
   a. Drag-and-drop the file into the chat window (Win32 drag simulation)
   b. Ctrl+Shift+F -> file picker dialog -> type path -> Enter
4. Wait for file to finish uploading (optional)

Parameters:
    to (str): contact or group name
    file_path (str): absolute path to the file/image
"""
from __future__ import annotations

from .base import BaseOperation, OperationContext, OperationResult, OperationStatus
from .registry import register_operation


@register_operation("send_file")
class SendFileOperation(BaseOperation):
    description = "Send a file or image to a contact or group"
    requires_confirmation = False

    async def execute(self, ctx: OperationContext, params: dict) -> OperationResult:
        """TODO: implement send file workflow.

        Preferred approach (Ctrl+Shift+F):
        1. ctx.controller.activate_window()
        2. Open target chat (search + Enter)
        3. ctx.controller.press_keys('Ctrl', 'Shift', 'f')   # open file dialog
        4. ctx.controller._delay()
        5. ctx.controller.type_text(params['file_path'])       # type file path
        6. ctx.controller.press_keys('Enter')                  # select file
        7. ctx.controller.press_keys('Enter')                  # confirm send

        Alternative (drag-and-drop):
        1. Open target chat
        2. Get window rect, calculate drop target (message input area center)
        3. ctx.controller.drag(file_icon_x, file_icon_y, drop_x, drop_y)
        - Requires the file to be visible on desktop/explorer first

        Notes:
        - Verify file exists before attempting
        - Large files may need upload wait time
        """
        raise NotImplementedError(
            "Implement: open chat -> file dialog -> type path -> send"
        )
