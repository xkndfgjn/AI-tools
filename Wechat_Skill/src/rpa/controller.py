"""Core RPA Controller - atomic operations on WeChat desktop window.

Responsibilities:
- Find and activate the WeChat window via the UI Automation control tree
- Control-tree first element location (find_control / find_all_controls)
- Mouse: click, double-click, right-click, drag
- Keyboard: type text (clipboard paste for CJK), press key combos
- Screenshot: capture full screen or window region

All methods are SYNCHRONOUS (blocking). Call from async context via asyncio.to_thread().
"""
from __future__ import annotations

import ctypes
import math
import threading
import time
from typing import Any, Optional

import numpy as np

try:
    import uiautomation as uia
    _UIA_AVAILABLE = True
except Exception:  # pragma: no cover - uiautomation is Windows-only
    uia = None  # type: ignore
    _UIA_AVAILABLE = False

try:
    import pyperclip
    _CLIP_AVAILABLE = True
except Exception:  # pragma: no cover
    pyperclip = None  # type: ignore
    _CLIP_AVAILABLE = False

from .finder import Element
from .screenshot import ScreenshotUtil

# Win32 constants
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MOVE = 0x0001
SW_RESTORE = 9
SW_SHOW = 5


class RpaController:
    """Atomic RPA operations targeting the WeChat desktop window."""

    def __init__(self, config: dict):
        self.config = config
        self._window_handle: Optional[int] = None
        self._window_control: Optional[Any] = None
        self._window_rect: Optional[tuple[int, int, int, int]] = None
        self._screenshot = ScreenshotUtil(config)
        self._user32 = ctypes.windll.user32
        self._com_tls = threading.local()
        # DPI awareness (critical for correct coordinates on HiDPI displays)
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass  # may already be set or not supported

    def _ensure_com(self):
        """Initialize COM on the current thread (required by uiautomation)."""
        if not _UIA_AVAILABLE:
            return
        if not getattr(self._com_tls, "initialized", False):
            try:
                ctypes.windll.ole32.CoInitialize(None)
            except Exception:
                pass
            self._com_tls.initialized = True

    # ── Window Management ──────────────────────────────────────

    def find_wechat_window(self) -> Optional[int]:
        """Locate the WeChat main window. Returns HWND or None.

        Strategy:
        1. UI Automation by window name (new WeChat Qt version)
        2. UI Automation by class + name (legacy WeChat version)
        3. Enumerate top-level windows by name
        """
        self._ensure_com()

        if not _UIA_AVAILABLE:
            return None

        wechat = self.config.get("wechat", {})
        window_name = wechat.get("window_name", "微信")
        class_name = wechat.get("class_name", "WeChatMainWndForPC")

        # 清理旧状态，避免拿到旧 HWND
        self._window_handle = None
        self._window_control = None

        # 1. 新版微信：直接通过窗口名称查找
        # 实测新版微信:
        # Name = 微信
        # ClassName = Qt51514QWindowIcon
        try:
            win = uia.WindowControl(
                searchDepth=1,
                Name=window_name
            )

            if win.Exists(2, 0.5):
                hwnd = win.NativeWindowHandle

                if hwnd:
                    self._window_control = win
                    self._window_handle = hwnd
                    self._update_rect()
                    return hwnd

        except Exception:
            pass


        # 2. 兼容旧版微信：ClassName + Name
        try:
            if class_name:
                win = uia.WindowControl(
                    searchDepth=1,
                    ClassName=class_name,
                    Name=window_name
                )

                if win.Exists(2, 0.5):
                    hwnd = win.NativeWindowHandle

                    if hwnd:
                        self._window_control = win
                        self._window_handle = hwnd
                        self._update_rect()
                        return hwnd

        except Exception:
            pass


        # 3. 枚举顶层窗口，通过 Name 查找
        try:
            root = uia.GetRootControl()

            for c in root.GetChildren():
                try:
                    if c.ControlType != uia.ControlType.WindowControl:
                        continue

                    cname = (getattr(c, "Name", "") or "")

                    if window_name in cname:
                        hwnd = getattr(c, "NativeWindowHandle", 0)

                        if hwnd:
                            self._window_control = c
                            self._window_handle = hwnd
                            self._update_rect()
                            return hwnd

                except Exception:
                    continue

        except Exception:
            pass


        self._window_handle = None
        self._window_control = None
        return None

    def activate_window(self) -> bool:
        """Bring WeChat to foreground. Returns True if successful."""
        self._ensure_com()
        if not _UIA_AVAILABLE:
            return False

        hwnd = self.find_wechat_window()
        if not hwnd:
            return False

        # Work around Windows foreground-lock by attaching thread inputs
        fg = self._user32.GetForegroundWindow()
        if fg:
            cur_thread = ctypes.windll.kernel32.GetCurrentThreadId()
            fg_thread = self._user32.GetWindowThreadProcessId(fg, None)
            if cur_thread != fg_thread:
                self._user32.AttachThreadInput(cur_thread, fg_thread, True)

        self._user32.ShowWindow(hwnd, SW_RESTORE)
        self._user32.SetForegroundWindow(hwnd)

        if fg and cur_thread != fg_thread:
            self._user32.AttachThreadInput(cur_thread, fg_thread, False)

        self._update_rect()
        self._delay(500)
        return True

    def get_window_rect(self) -> Optional[tuple[int, int, int, int]]:
        """Return (left, top, right, bottom) of the WeChat window in screen coords."""
        self._ensure_com()
        if self._window_handle:
            rect = ctypes.wintypes.RECT()
            if self._user32.GetWindowRect(self._window_handle, ctypes.byref(rect)):
                self._window_rect = (rect.left, rect.top, rect.right, rect.bottom)
                return self._window_rect

        if self._window_control and self._window_control.Exists(0, 0):
            try:
                self._window_rect = tuple(self._window_control.BoundingRectangle)
                return self._window_rect
            except Exception:
                pass

        return None

    def _update_rect(self) -> Optional[tuple[int, int, int, int]]:
        return self.get_window_rect()

    # ── Control Tree ───────────────────────────────────────────

    def _control_matches(
        self,
        control: Any,
        name: Optional[str],
        class_name: Optional[str],
        automation_id: Optional[str],
        control_type: Optional[str],
        text_contains: bool,
    ) -> bool:
        try:
            if name is not None:
                cname = getattr(control, "Name", "") or ""
                if text_contains:
                    if name not in cname:
                        return False
                else:
                    if name != cname:
                        return False

            if class_name is not None and (getattr(control, "ClassName", "") or "") != class_name:
                return False

            if automation_id is not None and (getattr(control, "AutomationId", "") or "") != automation_id:
                return False

            if control_type is not None:
                type_name = (getattr(control, "ControlTypeName", "") or "").lower()
                if type_name != control_type.lower():
                    return False

            return True
        except Exception:
            return False

    def _control_to_element(self, control: Any, strategy: str = "control_tree") -> Optional[Element]:
        try:
            rect = tuple(control.BoundingRectangle)
            x = (rect[0] + rect[2]) // 2
            y = (rect[1] + rect[3]) // 2
            return Element(
                x=x,
                y=y,
                width=rect[2] - rect[0],
                height=rect[3] - rect[1],
                confidence=1.0,
                strategy=strategy,
            )
        except Exception:
            return None

    def find_control(
        self,
        name: Optional[str] = None,
        class_name: Optional[str] = None,
        automation_id: Optional[str] = None,
        control_type: Optional[str] = None,
        text_contains: bool = True,
        depth: int = 5,
        found_index: int = 1,
    ) -> Optional[Element]:
        """Find a UI element inside the WeChat window via the control tree.

        Returns an Element with screen-absolute center coordinates, or None.
        """
        self._ensure_com()
        if not _UIA_AVAILABLE:
            return None

        if self._window_control is None or not self._window_control.Exists(0, 0):
            if not self.find_wechat_window():
                return None

        try:
            control = uia.FindControl(
                self._window_control,
                lambda c, d: self._control_matches(c, name, class_name, automation_id, control_type, text_contains),
                maxDepth=depth,
                foundIndex=found_index,
            )
            if control and control.Exists(0, 0):
                return self._control_to_element(control, "control_tree")
        except Exception:
            pass
        return None

    def find_all_controls(
        self,
        name: Optional[str] = None,
        class_name: Optional[str] = None,
        automation_id: Optional[str] = None,
        control_type: Optional[str] = None,
        text_contains: bool = True,
        depth: int = 5,
    ) -> list[Element]:
        """Find all matching UI elements inside the WeChat window."""
        infos = self.find_controls_info(
            name=name,
            class_name=class_name,
            automation_id=automation_id,
            control_type=control_type,
            text_contains=text_contains,
            depth=depth,
        )
        elements = []
        for info in infos:
            try:
                rect = info["rect"]
                x = (rect[0] + rect[2]) // 2
                y = (rect[1] + rect[3]) // 2
                elements.append(Element(
                    x=x, y=y,
                    width=rect[2] - rect[0],
                    height=rect[3] - rect[1],
                    confidence=1.0,
                    strategy="control_tree",
                ))
            except Exception:
                continue
        return elements

    def find_controls_info(
        self,
        name: Optional[str] = None,
        class_name: Optional[str] = None,
        automation_id: Optional[str] = None,
        control_type: Optional[str] = None,
        text_contains: bool = True,
        depth: int = 5,
    ) -> list[dict]:
        """Find matching controls and return their metadata (including names).

        Useful for operations like list_sessions that need readable text rather
        than just screen coordinates.
        """
        self._ensure_com()
        if not _UIA_AVAILABLE:
            return []

        if self._window_control is None or not self._window_control.Exists(0, 0):
            if not self.find_wechat_window():
                return []

        results: list[dict] = []
        index = 1
        while True:
            try:
                control = uia.FindControl(
                    self._window_control,
                    lambda c, d: self._control_matches(c, name, class_name, automation_id, control_type, text_contains),
                    maxDepth=depth,
                    foundIndex=index,
                )
                if not control or not control.Exists(0, 0):
                    break
                results.append({
                    "name": getattr(control, "Name", "") or "",
                    "class_name": getattr(control, "ClassName", "") or "",
                    "control_type": getattr(control, "ControlTypeName", "") or "",
                    "rect": tuple(control.BoundingRectangle),
                })
                index += 1
            except Exception:
                break
        return results

    # ── Mouse ──────────────────────────────────────────────────

    def click(self, x: int, y: int) -> None:
        """Left-click at absolute screen coordinates (x, y)."""
        self._delay(100)
        self._user32.SetCursorPos(x, y)
        ctypes.windll.user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        self._delay(50)
        ctypes.windll.user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        self._delay(100)

    def double_click(self, x: int, y: int) -> None:
        """Double left-click at (x, y)."""
        self.click(x, y)
        self._delay(100)
        self.click(x, y)

    def right_click(self, x: int, y: int) -> None:
        """Right-click at (x, y)."""
        self._delay(100)
        self._user32.SetCursorPos(x, y)
        ctypes.windll.user32.mouse_event(MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, 0)
        self._delay(50)
        ctypes.windll.user32.mouse_event(MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)
        self._delay(100)

    def drag(self, x1: int, y1: int, x2: int, y2: int, duration: float = 0.5, steps: int = 20) -> None:
        """Drag from (x1,y1) to (x2,y2)."""
        if steps < 2:
            steps = 2
        self._delay(100)
        self._user32.SetCursorPos(x1, y1)
        ctypes.windll.user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        sleep_per = duration / steps
        for i in range(1, steps + 1):
            t = i / steps
            xi = int(x1 + (x2 - x1) * t)
            yi = int(y1 + (y2 - y1) * t)
            self._user32.SetCursorPos(xi, yi)
            time.sleep(sleep_per)
        ctypes.windll.user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        self._delay(200)

    # ── Keyboard ──────────────────────────────────────────────

    def type_text(self, text: str) -> None:
        """Input text via clipboard paste (reliable for CJK characters)."""
        self._ensure_com()
        if not text:
            return

        if _CLIP_AVAILABLE:
            try:
                original = pyperclip.paste()
            except Exception:
                original = ""
            pyperclip.copy(text)
            self._delay(100)
            self.press_keys("Ctrl", "v")
            self._delay(100)
            try:
                pyperclip.copy(original)
            except Exception:
                pass
        elif _UIA_AVAILABLE:
            uia.SendKeys(text)
            self._delay(100)

    @staticmethod
    def _build_sendkeys(keys: tuple[str, ...]) -> str:
        """Convert human key names to uiautomation SendKeys syntax."""
        special = {
            "enter": "{Enter}",
            "return": "{Enter}",
            "esc": "{Esc}",
            "escape": "{Esc}",
            "tab": "{Tab}",
            "space": " ",
            "backspace": "{Back}",
            "delete": "{Delete}",
        }

        if len(keys) == 1:
            k = keys[0]
            return special.get(k.lower(), k)

        modifiers = []
        main_key = ""
        for k in keys:
            kl = k.lower()
            if kl in ("ctrl", "control"):
                modifiers.append("{Ctrl}")
            elif kl == "shift":
                modifiers.append("{Shift}")
            elif kl == "alt":
                modifiers.append("{Alt}")
            else:
                main_key = special.get(kl, k)
        return "".join(modifiers) + main_key

    def press_keys(self, *keys: str) -> None:
        """Press a key combination, e.g. press_keys('Ctrl', 'f') or press_keys('Enter')."""
        self._ensure_com()
        if not keys or not _UIA_AVAILABLE:
            return
        ks = self._build_sendkeys(keys)
        uia.SendKeys(ks)
        self._delay(150)

    # ── Screenshot ─────────────────────────────────────────────

    def screenshot(self, region: Optional[tuple[int, int, int, int]] = None) -> np.ndarray:
        """Capture screen or a specific region. Returns BGR ndarray."""
        if region is None:
            rect = self.get_window_rect()
            if rect:
                region = rect
        return self._screenshot.capture(region)

    def save_screenshot(self, image: Optional[np.ndarray] = None,
                        region: Optional[tuple[int, int, int, int]] = None) -> str:
        """Capture (if needed) and persist a screenshot. Returns the file path."""
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
