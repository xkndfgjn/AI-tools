"""WeChat native OCR backend - uses the OCR engine shipped with WeChat 4.x.

Calls the offline ``wxocr.dll`` (WeChat's own OCR engine) through the
pre-built ``wcocr.pyd`` extension (see src/rpa/vendor/wcocr/README.md for
provenance). Recognition quality is tuned by Tencent for Chinese chat
content, typically beating generic models (RapidOCR etc.) on chat bubbles,
mixed CJK/emoji text and dense layouts. No model download, no network.

Runtime inputs (auto-detected, overridable via config):
- ``wxocr.dll`` lives under
  ``%APPDATA%\\Tencent\\xwechat\\XPlugin\\Plugins\\WeChatOcr\\<ver>\\extracted\\wxocr.dll``
  (the numeric dir changes with WeChat updates; we pick the largest version).
- WeChat's runtime dir is the version folder containing ``mmmojo_64.dll``
  (e.g. ``D:\\Weixin\\4.1.12.55``). The OCR sub-process is launched with
  ``weixin.exe`` found in the PARENT of that folder.

Normalized output (identical shape to the RapidOCR backend so call sites
never change):
    {
        "text": str,
        "confidence": float,
        "box": [[x,y], [x,y], [x,y], [x,y]],  # 4 corners, image-local coords
        "center_x": int,
        "center_y": int,
        "width": int,
        "height": int,
    }
"""
from __future__ import annotations

import os
import re
import threading
import tempfile
from pathlib import Path
from typing import Any, Optional

import cv2

# Pre-built extension; import failure is non-fatal (backend simply unavailable).
try:
    from .vendor.wcocr import wcocr  # type: ignore
    _WCOCR_AVAILABLE = True
except Exception:  # pragma: no cover - import is optional at runtime
    wcocr = None  # type: ignore
    _WCOCR_AVAILABLE = False


# ---------------------------------------------------------------------------
# Path discovery
# ---------------------------------------------------------------------------

def _version_key(name: str) -> tuple:
    """Sort numeric version dirs numerically ('8092' > '8011')."""
    parts = re.findall(r"\d+", name)
    return tuple(int(p) for p in parts) if parts else (0,)


def find_wxocr_dll() -> Optional[str]:
    """Locate the newest wxocr.dll shipped with the installed WeChat 4.x.

    Returns the absolute path or None. Raises nothing.
    """
    if not _WCOCR_AVAILABLE:
        return None
    try:
        base = Path(os.environ.get("APPDATA", "")) / "Tencent" / "xwechat" \
            / "XPlugin" / "Plugins" / "WeChatOcr"
    except Exception:
        return None
    if not base.is_dir():
        return None
    candidates = []
    for ver_dir in base.iterdir():
        if not ver_dir.is_dir():
            continue
        dll = ver_dir / "extracted" / "wxocr.dll"
        if dll.is_file():
            candidates.append(dll)
    if not candidates:
        return None
    # Newest version dir first.
    candidates.sort(key=lambda p: _version_key(p.parent.parent.name), reverse=True)
    return str(candidates[0])


def find_wechat_dir() -> Optional[str]:
    """Locate the WeChat runtime version folder (contains mmmojo_64.dll).

    Standard install layout: ``<root>\\<version>\\mmmojo_64.dll`` where
    ``<root>`` also holds ``weixin.exe`` (the OCR sub-process launcher).
    Checks common roots; override via config for non-standard installs.
    """
    roots = [
        r"C:\Program Files\Tencent\Weixin",
        r"C:\Program Files (x86)\Tencent\Weixin",
        r"D:\Weixin",
        str(Path(os.environ.get("LOCALAPPDATA", "")) / "Tencent" / "Weixin"),
    ]
    best: Optional[tuple] = None
    best_path: Optional[str] = None
    for root in roots:
        root_path = Path(root)
        if not root_path.is_dir():
            continue
        for sub in root_path.iterdir():
            if not sub.is_dir():
                continue
            if (sub / "mmmojo_64.dll").is_file():
                key = _version_key(sub.name)
                if best is None or key > best:
                    best = key
                    best_path = str(sub)
    return best_path


# ---------------------------------------------------------------------------
# Backend
# ---------------------------------------------------------------------------

class WeChatOcrBackend:
    """Thin wrapper over wcocr.pyd exposing the normalized extract() API.

    Singleton per process: wcocr.init() spawns a WeChat OCR sub-process once;
    repeated init/destroy is expensive and racy.
    """

    _instance: Optional["WeChatOcrBackend"] = None
    _lock = threading.Lock()

    def __init__(self, config: Optional[dict] = None):
        self.config = config or {}
        self._initialized = False
        self._ok = False
        self._init_error: Optional[str] = None
        self._ocr_lock = threading.Lock()  # wcocr sync calls are not thread-safe

    @classmethod
    def get(cls, config: Optional[dict] = None) -> "WeChatOcrBackend":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(config)
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        with cls._lock:
            if cls._instance is not None:
                cls._instance.shutdown()
                cls._instance = None

    def _resolve_paths(self) -> tuple[Optional[str], Optional[str]]:
        """Return (wxocr_dll, wechat_dir) from config or auto-discovery."""
        cfg = self.config.get("rpa", {}).get("wechat_ocr", {}) or {}
        dll = cfg.get("wxocr_dll") or find_wxocr_dll()
        wdir = cfg.get("wechat_dir") or find_wechat_dir()
        return (dll, wdir)

    def _ensure(self) -> bool:
        if self._initialized:
            return self._ok
        self._initialized = True
        if not _WCOCR_AVAILABLE:
            self._init_error = "wcocr.pyd not importable (missing vendor binary?)"
            return False
        dll, wdir = self._resolve_paths()
        if not dll or not os.path.isfile(dll):
            self._init_error = (
                "wxocr.dll not found. Install/update WeChat 4.x or set "
                "config rpa.wechat_ocr.wxocr_dll explicitly."
            )
            return False
        if not wdir or not os.path.isdir(wdir):
            self._init_error = (
                "WeChat runtime dir not found. Set config "
                "rpa.wechat_ocr.wechat_dir explicitly."
            )
            return False
        try:
            wcocr.init(dll, wdir)
            self._ok = True
        except Exception as e:  # pragma: no cover - depends on user env
            self._init_error = f"wcocr.init failed: {e}"
            self._ok = False
        return self._ok

    @property
    def available(self) -> bool:
        return self._ensure()

    @property
    def init_error(self) -> Optional[str]:
        self._ensure()
        return self._init_error

    def shutdown(self) -> None:
        """Tear down the OCR sub-process (called on reset/app shutdown)."""
        if self._initialized and self._ok and wcocr is not None:
            try:
                wcocr.destroy()
            except Exception:
                pass
        self._initialized = False
        self._ok = False

    def extract(self, image) -> list[dict]:
        """OCR an image (BGR ndarray) and return normalized item dicts.

        wcocr.ocr() requires an absolute image file path, so the array is
        written to a temp PNG first, then removed after OCR.
        """
        if not self._ensure():
            return []
        if image is None:
            return []

        tmp_path: Optional[str] = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                tmp_path = f.name
            # cv2.imwrite accepts BGR ndarrays and writes a proper PNG.
            if not cv2.imwrite(tmp_path, image):
                return []
            with self._ocr_lock:
                raw = wcocr.ocr(tmp_path)
        except Exception:
            return []
        finally:
            if tmp_path:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

        return self._normalize(raw)

    @staticmethod
    def _normalize(raw: Any) -> list[dict]:
        """Convert wcocr result dict to the shared normalized shape."""
        if not isinstance(raw, dict):
            return []
        if raw.get("errcode") not in (0, None):
            return []
        items: list[dict] = []
        for block in raw.get("ocr_response") or []:
            text = str(block.get("text") or "").strip()
            if not text:
                continue
            try:
                left = float(block.get("left", 0))
                top = float(block.get("top", 0))
                right = float(block.get("right", 0))
                bottom = float(block.get("bottom", 0))
            except (TypeError, ValueError):
                continue
            if right < left or bottom < top:
                continue
            items.append({
                "text": text,
                "confidence": float(block.get("rate") or 0.0),
                "box": [
                    [left, top], [right, top],
                    [right, bottom], [left, bottom],
                ],
                "center_x": int(round((left + right) / 2)),
                "center_y": int(round((top + bottom) / 2)),
                "width": int(round(right - left)),
                "height": int(round(bottom - top)),
            })
        return items
