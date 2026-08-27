"""Send a file or image to a WeChat contact or group."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

import cv2
import numpy as np

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
        to = "".join(str(to).split())
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

        # Re-activate after opening the chat: the search result click can leave
        # the window without foreground focus on some Qt WeChat builds.
        if not await asyncio.to_thread(ctx.controller.activate_window):
            return OperationResult(
                status=OperationStatus.FAILED,
                message="WeChat window could not be activated before sending",
            )

        # Qt WeChat 4.x does not reliably handle Ctrl+Shift+F. Click the file
        # button found by a screenshot template, never by OCR or a guessed
        # coordinate.
        rect = ctx.controller.get_window_rect()
        if rect is None:
            return OperationResult(
                status=OperationStatus.FAILED,
                message="No window rect",
            )
        button_cfg = ctx.config.get("send_file", {}).get("file_button", {})
        located = await asyncio.to_thread(
            _find_file_button_by_template, ctx, rect, button_cfg
        )
        if located is None:
            return OperationResult(
                status=OperationStatus.FAILED,
                message="File button template was not found; file was not sent",
            )
        x, y, confidence = located
        await asyncio.to_thread(ctx.controller.click, x, y)
        await sleep_ms(ctx, button_cfg.get("dialog_settle_ms", 800))

        await asyncio.to_thread(ctx.controller.type_text, os.path.abspath(file_path))
        await sleep_ms(ctx, button_cfg.get("path_settle_ms", 400))

        # Confirm file selection in the dialog
        await asyncio.to_thread(ctx.controller.press_keys, "Enter")
        await sleep_ms(ctx, button_cfg.get("selection_settle_ms", 800))

        # Confirm send after the file dialog closes. A configurable second
        # Enter supports versions where the preview needs explicit approval.
        await asyncio.to_thread(ctx.controller.press_keys, "Enter")
        await sleep_ms(ctx, button_cfg.get("send_settle_ms", 1000))

        return OperationResult(
            status=OperationStatus.SUCCESS,
            data={"to": to, "file_path": file_path, "button_confidence": confidence},
            message=f"File sent to '{to}'",
        )


def _find_file_button_by_template(ctx, rect, button_cfg):
    """Match the file icon feature model and return an absolute coordinate."""
    model_name = button_cfg.get("feature_model", "wechat_file_button_features.npz")
    template_dir = ctx.config.get("rpa", {}).get("template_dir", "./config/templates")
    model_path = Path(model_name)
    if not model_path.is_absolute():
        model_path = Path(template_dir) / model_path
    if not model_path.exists():
        return None
    model = np.load(model_path)
    model_keypoints = model["keypoints"].astype(np.float32)
    model_descriptors = model["descriptors"].astype(np.float32)
    model_center = model["center"].astype(np.float32)

    left, top, right, bottom = rect
    width = right - left
    height = bottom - top
    roi_left = int(width * float(button_cfg.get("roi_left_ratio", 0.35)))
    roi_top = int(height * float(button_cfg.get("roi_top_ratio", 0.86)))
    roi_right = int(width * float(button_cfg.get("roi_right_ratio", 0.75)))
    roi_bottom = int(height * float(button_cfg.get("roi_bottom_ratio", 0.99)))
    screenshot = ctx.controller.screenshot(rect)
    roi = cv2.cvtColor(screenshot[roi_top:roi_bottom, roi_left:roi_right], cv2.COLOR_BGR2GRAY)
    detector = getattr(cv2, "SIFT_create")(nfeatures=800)
    scene_keypoints, scene_descriptors = detector.detectAndCompute(roi, None)
    if scene_descriptors is None or len(scene_keypoints) < 4:
        return None
    matcher = cv2.BFMatcher(cv2.NORM_L2)
    pairs = matcher.knnMatch(model_descriptors, scene_descriptors, k=2)
    ratio = float(button_cfg.get("feature_ratio", 0.75))
    good = [first for first, second in pairs if first.distance < ratio * second.distance]
    if len(good) < int(button_cfg.get("min_good_matches", 6)):
        return None
    source: Any = np.asarray([model_keypoints[m.queryIdx] for m in good], dtype=np.float32)
    destination: Any = np.asarray([scene_keypoints[m.trainIdx].pt for m in good], dtype=np.float32)
    transform, mask = cv2.findHomography(source, destination, cv2.RANSAC, 5.0)  # type: ignore[reportCallIssue]
    if transform is None or mask is None:
        return None
    inliers = int(mask.ravel().sum())
    if inliers < int(button_cfg.get("min_inliers", 6)):
        return None
    mapped_center = cv2.transform(model_center.reshape(1, 1, 2), transform)[0, 0]
    center_x = roi_left + int(mapped_center[0])
    center_y = roi_top + int(mapped_center[1])
    confidence = min(1.0, inliers / max(8.0, len(model_keypoints)))
    return left + center_x, top + center_y, float(confidence)
