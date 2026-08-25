"""Screenshot utility - capture screen or window regions.

Uses Pillow ImageGrab for screen capture and returns numpy arrays (BGR)
compatible with OpenCV operations.
"""
from __future__ import annotations

import os
from typing import Optional

import numpy as np
from PIL import ImageGrab


class ScreenshotUtil:
    """Screen capture utility."""

    def __init__(self, config: dict):
        self.config = config
        self._screenshot_dir = config.get("rpa", {}).get("screenshot_dir", "./data/screenshots")

    def capture(self, region: Optional[tuple[int, int, int, int]] = None) -> np.ndarray:
        """Capture the screen or a specific region.

        Args:
            region: (left, top, right, bottom) in screen coordinates.
                    If None, captures the full primary screen.

        Returns:
            BGR numpy array (OpenCV-compatible format).
        """
        img = ImageGrab.grab(bbox=region)  # PIL Image, RGB order
        arr = np.array(img)                # (H, W, 3) RGB
        # Convert RGB -> BGR and copy to make the array C-contiguous
        # (cv2.imwrite rejects arrays with negative strides).
        return arr[:, :, ::-1].copy()

    def save(self, image: np.ndarray, filename: str) -> str:
        """Save a screenshot array to file. Returns the file path.

        Args:
            image: BGR numpy array (as returned by capture()).
            filename: base filename (no directory). Directory is taken from config.

        Returns:
            Path to the saved file.
        """
        import cv2

        os.makedirs(self._screenshot_dir, exist_ok=True)
        path = filename if os.path.isabs(filename) else os.path.join(self._screenshot_dir, filename)
        cv2.imwrite(path, image)
        return path
