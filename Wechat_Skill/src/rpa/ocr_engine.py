"""RapidOCR engine wrapper - shared singleton for finder and operations.

Replaces EasyOCR. Reasons:
- Better Chinese recognition (PP-OCRv6 models by default).
- CPU-only via onnxruntime, no torch dependency, lighter install.
- Faster on small image regions.

The underlying RapidOCR instance is lazy-initialized once (it loads/downloads
ONNX models on first use). Both the finder strategies and the operation
helpers consume the same normalized dict output so the OCR backend can be
swapped without touching call sites.

Output item shape:
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


class OcrEngine:
    """Lazy singleton wrapping RapidOCR.

    Usage:
        engine = OcrEngine.get(config)
        if engine.available:
            items = engine.extract(image_ndarray)
    """

    _instance: Optional["OcrEngine"] = None
    _lock = threading.Lock()

    def __init__(self, config: Optional[dict] = None):
        self.config = config or {}
        self._engine: Any = None   # RapidOCR instance, or False if unavailable
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
        """Drop the singleton (mainly for tests / config reload)."""
        with cls._lock:
            cls._instance = None

    def _ensure(self):
        """Initialize the RapidOCR engine on first use. Returns the engine or False."""
        if self._initialized:
            return self._engine
        self._initialized = True
        if not _RAPID_AVAILABLE:
            self._engine = False
            return False
        try:
            self._engine = RapidOCR()
        except Exception:
            self._engine = False
        return self._engine

    @property
    def available(self) -> bool:
        """True if the OCR engine initialized successfully."""
        return self._ensure() is not False

    def extract(self, image) -> list[dict]:
        """Run OCR on an image (ndarray / file path / URL).

        Returns a list of normalized item dicts (see module docstring).
        Returns [] on failure or when no text is found.
        """
        eng = self._ensure()
        if eng is False:
            return []
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
