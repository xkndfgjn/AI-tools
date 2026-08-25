"""Core RPA Controller - atomic operations on WeChat desktop window.

Responsibilities:
- Find and activate the WeChat window
- Mouse: click, double-click, right-click, drag
- Keyboard: type text (via clipboard paste for CJK), press key combos
- Screenshot: capture full screen or window region

All methods are SYNCHRONOUS (blocking). Call from async context via run_in_executor().
"""
from __future__ import annotations

import ctypes
import time
from typing import Optional

import numpy as np

try:
    import uiautomation as uia
    _UIA_AVAILABLE = True
except ImportError:
    _UIA_AVAILABLE = False

from .screenshot import ScreenshotUtil


class RpaController:
    """Atomic RPA operations targeting the WeChat desktop window."""

    def __init__(self, config: dict):
        self.config = config
        self._window_handle: Optional[int] = None
        self._window_rect: Optional[tuple[int, int, int, int]] = None
        self._screenshot = ScreenshotUtil(config)
        self._user32 = ctypes.windll.user32
        # DPI awareness (critical for correct coordinates on HiDPI displays)
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass  # may already be set or not supported

    # ── Window Management ──────────────────────────────────────

    def find_wechat_window(self) -> Optional[int]:
        """Locate the WeChat main window. Returns window handle (HWND) or None.

        TODO: implement using uiautomation WindowControl or Win32 FindWindow.
        - Search by window name (config["wechat"]["window_name"]) or process name.
        - Store handle in self._window_handle.
        """
        raise NotImplementedError

    def activate_window(self) -> bool:
        """Bring WeChat to foreground. Returns True if successful.

        TODO: implement using Win32 SetForegroundWindow + ShowWindow(SW_RESTORE).
        - Handle the foreground-lock timeout (AttachThreadInput trick if needed).
        - Add a small delay after activation for UI to settle.
        """
        raise NotImplementedError

    def get_window_rect(self) -> Optional[tuple[int, int, int, int]]:
        """Return (left, top, right, bottom) of the WeChat window in screen coords.

        TODO: implement using Win32 GetWindowRect.
        - Cache result in self._window_rect.
        - Handle minimized/hidden window.
        """
        raise NotImplementedError

    # ── Mouse ──────────────────────────────────────────────────

    def click(self, x: int, y: int) -> None:
        """Left-click at absolute screen coordinates (x, y).

        TODO: implement using ctypes SetCursorPos + mouse_event(MOUSEEVENTF_LEFTDOWN|UP).
        - Add configurable pre/post delay.
        """
        raise NotImplementedError

    def double_click(self, x: int, y: int) -> None:
        """Double left-click at (x, y)."""
        # TODO: call click() twice with short interval
        raise NotImplementedError

    def right_click(self, x: int, y: int) -> None:
        """Right-click at (x, y)."""
        # TODO: mouse_event with MOUSEEVENTF_RIGHTDOWN|UP
        raise NotImplementedError

    def drag(self, x1: int, y1: int, x2: int, y2: int, duration: float = 0.5, steps: int = 20) -> None:
        """Drag from (x1,y1) to (x2,y2) over *duration* seconds in *steps* increments.

        TODO: implement using SetCursorPos + mouse_event in a loop.
        - Reference: see ARCHITECTURE.md mouse_drag example.
        """
        raise NotImplementedError

    # ── Keyboard ──────────────────────────────────────────────

    def type_text(self, text: str) -> None:
        """Input text via clipboard paste (reliable for CJK characters).

        TODO: implement using:
        - Copy text to clipboard (win32clipboard or pyperclip)
        - Ctrl+V paste
        This is more reliable than SendKeys for Chinese text.
        """
        raise NotImplementedError

    def press_keys(self, *keys: str) -> None:
        """Press a key combination, e.g. press_keys('Ctrl', 'f') or press_keys('Enter').

        TODO: implement using uiautomation.SendKeys or ctypes keybd_event.
        - Map key names: 'Ctrl' -> VK_CONTROL, 'Enter' -> VK_RETURN, etc.
        """
        raise NotImplementedError

    # ── Screenshot ─────────────────────────────────────────────

    def screenshot(self, region: Optional[tuple[int, int, int, int]] = None) -> np.ndarray:
        """Capture screen or a specific region. Returns BGR ndarray.

        Args:
            region: (left, top, right, bottom) or None for WeChat window region.
        """
        return self._screenshot.capture(region)

    def save_screenshot(self, image: Optional[np.ndarray] = None,
                        region: Optional[tuple[int, int, int, int]] = None) -> str:
        """Capture (if needed) and persist a screenshot. Returns the file path.

        Args:
            image: existing BGR ndarray; if None, a new capture is taken.
            region: (left, top, right, bottom) for the capture, or None.

        Returns:
            Path to the saved PNG file.
        """
        if image is None:
            image = self.screenshot(region)
        filename = f"wechat_{time.time_ns()}.png"
        return self._screenshot.save(image, filename)

    # ── Utility ───────────────────────────────────────────────

    def _delay(self, ms: Optional[int] = None) -> None:
        """Sleep for config['rpa']['action_delay_ms'] or given ms."""
        ms = ms or self.config.get("rpa", {}).get("action_delay_ms", 300)
        time.sleep(ms / 1000.0)

    def screen_to_window(self, x: int, y: int) -> tuple[int, int]:
        """Convert absolute screen coords to window-relative coords."""
        if not self._window_rect:
            self.get_window_rect()
        l, t = self._window_rect[:2]
        return (x - l, y - t)

    def window_to_screen(self, x: int, y: int) -> tuple[int, int]:
        """Convert window-relative coords to absolute screen coords."""
        if not self._window_rect:
            self.get_window_rect()
        l, t = self._window_rect[:2]
        return (x + l, y + t)
