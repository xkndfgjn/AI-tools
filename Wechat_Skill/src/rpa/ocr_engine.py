"""OCR engine facade - shared singleton for finder and operations.

Backend selection is config-driven (``config['rpa']['ocr_engine']``):

- ``wechat``  - WeChat's own native OCR engine (wxocr.dll via wcocr.pyd).
                Best quality on chat content; zero model download; requires
                WeChat 4.x installed. See src/rpa/wechat_ocr.py.
- ``rapidocr`` - RapidOCR (PP-OCRv6, CPU/onnxruntime). Fallback that works
                without WeChat installed.
- ``auto`` (default) - try ``wechat`` first, fall back to ``rapidocr``.

All backends expose the same normalized dict output so finder strategies and
operation helpers never change:

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

import threading
from typing import Any, Optional

try:
    from rapidocr import RapidOCR
    _RAPID_AVAILABLE = True
except Exception:  # pragma: no cover - rapidocr is optional at import time
    RapidOCR = None  # type: ignore
    _RAPID_AVAILABLE = False

from .wechat_ocr import WeChatOcrBackend


class OcrEngine:
    """Lazy singleton selecting an OCR backend from config.

    Usage:
        engine = OcrEngine.get(config)
        if engine.available:
            items = engine.extract(image_ndarray)
    """

    _instance: Optional["OcrEngine"] = None
    _lock = threading.Lock()

    def __init__(self, config: Optional[dict] = None):
        self.config = config or {}
        self._engine: Any = None       # backend instance, or False if unavailable
        self._initialized = False

    @classmethod
    def get(cls, config: Optional[dict] = None) -> "OcrEngine":
        """Return the process-wide singleton (created on first call)."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(config)
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Drop the singleton (mainly for tests / config reload).

        Also tears down the WeChat OCR sub-process if it was initialized.
        """
        with cls._lock:
            WeChatOcrBackend.reset()
            cls._instance = None

    @property
    def backend_name(self) -> str:
        """Name of the currently active backend ('wechat'/'rapidocr'/None)."""
        eng = self._ensure()
        if eng is False:
            return "none"
        if isinstance(eng, WeChatOcrBackend):
            return "wechat"
        return "rapidocr"

    def _preferred(self) -> str:
        return str(self.config.get("rpa", {}).get("ocr_engine", "auto")).lower()

    def _ensure(self):
        """Initialize the configured backend on first use.

        Returns the backend instance, or False when none is available.
        """
        if self._initialized:
            return self._engine
        self._initialized = True

        preferred = self._preferred()
        chain = []
        if preferred == "wechat":
            chain = ["wechat"]
        elif preferred == "rapidocr":
            chain = ["rapidocr"]
        else:  # auto
            chain = ["wechat", "rapidocr"]

        for name in chain:
            eng = self._build(name)
            if eng is not False:
                self._engine = eng
                return eng
        self._engine = False
        return False

    def _build(self, name: str):
        """Build one backend by name; return False when unavailable."""
        if name == "wechat":
            try:
                backend = WeChatOcrBackend.get(self.config)
            except Exception:
                return False
            if backend.available:
                return backend
            return False
        if name == "rapidocr":
            if not _RAPID_AVAILABLE:
                return False
            try:
                return RapidOCR()
            except Exception:
                return False
        return False

    @property
    def available(self) -> bool:
        """True if an OCR backend initialized successfully."""
        return self._ensure() is not False

    def extract(self, image) -> list[dict]:
        """Run OCR on an image (BGR ndarray; also accepts file path/URL on
        the rapidocr backend).

        Returns a list of normalized item dicts (see module docstring).
        Returns [] on failure or when no text is found.
        """
        eng = self._ensure()
        if eng is False:
            return []
        try:
            if isinstance(eng, WeChatOcrBackend):
                return eng.extract(image)
            return self._extract_rapid(eng, image)
        except Exception:
            return []

    @staticmethod
    def _extract_rapid(eng, image) -> list[dict]:
        """Run the RapidOCR engine and normalize its output."""
        try:
            result = eng(image)
        except Exception:
            return []

        boxes = getattr(result, "boxes", None)
        txts = getattr(result, "txts", None)
        scores = getattr(result, "scores", None)
        # RapidOCR returns None for all three when no text is detected.
        if boxes is None or txts is None or scores is None:
            return []

        items: list[dict] = []
        for box, text, score in zip(boxes, txts, scores):
            try:
                xs = [float(p[0]) for p in box]
                ys = [float(p[1]) for p in box]
            except Exception:
                continue
            items.append({
                "text": str(text or ""),
                "confidence": float(score) if score is not None else 0.0,
                "box": [[float(p[0]), float(p[1])] for p in box],
                "center_x": int(sum(xs) / len(xs)),
                "center_y": int(sum(ys) / len(ys)),
                "width": int(max(xs) - min(xs)),
                "height": int(max(ys) - min(ys)),
            })
        return items
