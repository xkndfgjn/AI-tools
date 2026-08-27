"""Element Finder - strategy-chain UI element location.

Policy: control tree first, then template matching, then OCR, then AI vision.
This matches the project decision to rely on UI Automation as the primary
locator and fall back to computer vision only when the control tree is
insufficient (e.g., self-drawn lists, dynamic text).
"""
from __future__ import annotations

import base64
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

import numpy as np

if TYPE_CHECKING:
    from .controller import RpaController

try:
    import cv2
    _CV2_AVAILABLE = True
except Exception:  # pragma: no cover
    cv2 = None  # type: ignore
    _CV2_AVAILABLE = False

@dataclass
class FindTarget:
    """Describes what to find on screen.

    Control-tree fields (preferred):
        control_name: exact or substring match against Control.Name
        control_class: Control.ClassName
        control_type: Control.ControlTypeName, e.g. 'ListItemControl'
        automation_id: Control.AutomationId
        text_contains: if True, match substring; if False, exact match

    Vision fields (fallback):
        template: relative path to template image (for TemplateMatchStrategy)
        text: text to locate (for OCRStrategy / AIVisionStrategy)
        region: (l, t, r, b) to constrain search area within the screenshot
    """
    # control tree
    control_name: Optional[str] = None
    control_class: Optional[str] = None
    control_type: Optional[str] = None
    automation_id: Optional[str] = None
    # vision
    template: Optional[str] = None
    text: Optional[str] = None
    text_contains: bool = True
    region: Optional[tuple[int, int, int, int]] = None


@dataclass
class Element:
    """A located UI element in screen coordinates."""
    x: int               # screen-absolute center X
    y: int               # screen-absolute center Y
    width: int
    height: int
    confidence: float    # match score [0, 1]
    strategy: str        # which strategy found it


class FindStrategy(ABC):
    """Abstract base for element-finding strategies."""

    name: str = "base"

    def __init__(self, config: dict, controller: Optional["RpaController"] = None):
        self.config = config
        self.controller = controller

    @abstractmethod
    def supports(self, target: FindTarget) -> bool:
        """Whether this strategy can handle the given target."""
        ...

    @abstractmethod
    def find(self, screenshot: np.ndarray, target: FindTarget,
             window_offset: tuple[int, int] = (0, 0)) -> Optional[Element]:
        """Locate the target. Returns Element or None."""
        ...


class ControlTreeStrategy(FindStrategy):
    """Find element via the UI Automation control tree.

    Primary strategy: fast, precise, and independent of rendering.
    """

    name = "control_tree"

    def supports(self, target: FindTarget) -> bool:
        if self.controller is None:
            return False
        return any([
            target.control_name is not None,
            target.control_class is not None,
            target.control_type is not None,
            target.automation_id is not None,
            # if only text is given, we also try control tree by name
            target.text is not None,
        ])

    def find(self, screenshot: np.ndarray, target: FindTarget,
             window_offset: tuple[int, int] = (0, 0)) -> Optional[Element]:
        name = target.control_name or target.text
        controller = self.controller
        if controller is None:
            return None
        return controller.find_control(
            name=name,
            class_name=target.control_class,
            control_type=target.control_type,
            automation_id=target.automation_id,
            text_contains=target.text_contains,
            depth=5,
        )


class TemplateMatchStrategy(FindStrategy):
    """Find element by OpenCV template matching.

    Good for fixed UI icons (search button, send button, etc.).
    """

    name = "template_match"

    def __init__(self, config: dict, controller: Optional["RpaController"] = None):
        super().__init__(config, controller)
        self._template_dir = config.get("rpa", {}).get("template_dir", "./config/templates")
        self._threshold = config.get("rpa", {}).get("template_threshold", 0.8)

    def supports(self, target: FindTarget) -> bool:
        return target.template is not None

    def find(self, screenshot: np.ndarray, target: FindTarget,
             window_offset: tuple[int, int] = (0, 0)) -> Optional[Element]:
        if not _CV2_AVAILABLE:
            return None

        template_path = target.template
        if template_path is None:
            return None
        if not os.path.isabs(template_path):
            template_path = os.path.join(self._template_dir, template_path)
        if not os.path.exists(template_path):
            return None

        template = cv2.imread(template_path, cv2.IMREAD_COLOR)
        if template is None:
            return None

        # Optionally restrict search region
        roi = screenshot
        off_x, off_y = window_offset
        if target.region is not None:
            l, t, r, b = target.region
            l = max(0, l - off_x)
            t = max(0, t - off_y)
            r = min(screenshot.shape[1], r - off_x)
            b = min(screenshot.shape[0], b - off_y)
            if r <= l or b <= t:
                return None
            roi = screenshot[t:b, l:r]
            off_x += l
            off_y += t

        if roi.shape[0] < template.shape[0] or roi.shape[1] < template.shape[1]:
            return None

        # The import is optional; narrow the type before accessing OpenCV APIs.
        if not _CV2_AVAILABLE or cv2 is None:
            return None
        result = cv2.matchTemplate(roi, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)

        if max_val < self._threshold:
            return None

        h, w = template.shape[:2]
        center_x = off_x + max_loc[0] + w // 2
        center_y = off_y + max_loc[1] + h // 2
        return Element(
            x=center_x,
            y=center_y,
            width=w,
            height=h,
            confidence=float(max_val),
            strategy=self.name,
        )


class OCRStrategy(FindStrategy):
    """Find element by text recognition using RapidOCR.

    Good for dynamic text (contact names, message content).

    Note: EasyOCR was replaced by RapidOCR (PP-OCRv6, CPU, no torch dep).
    The shared engine singleton lives in src/rpa/ocr_engine.py.
    """

    name = "ocr"

    def __init__(self, config: dict, controller: Optional["RpaController"] = None):
        super().__init__(config, controller)
        from .ocr_engine import OcrEngine
        self._engine = OcrEngine.get(config)

    def supports(self, target: FindTarget) -> bool:
        return target.text is not None

    def find(self, screenshot: np.ndarray, target: FindTarget,
             window_offset: tuple[int, int] = (0, 0)) -> Optional[Element]:
        if not self._engine.available:
            return None

        roi = screenshot
        off_x, off_y = window_offset
        if target.region is not None:
            l, t, r, b = target.region
            l = max(0, l - off_x)
            t = max(0, t - off_y)
            r = min(screenshot.shape[1], r - off_x)
            b = min(screenshot.shape[0], b - off_y)
            if r <= l or b <= t:
                return None
            roi = screenshot[t:b, l:r]
            off_x += l
            off_y += t

        items = self._engine.extract(roi)
        query = target.text or ""
        best: Optional[Element] = None
        for it in items:
            text = it["text"] or ""
            matched = (query in text) if target.text_contains else (query == text)
            if not matched:
                continue
            el = Element(
                x=off_x + it["center_x"],
                y=off_y + it["center_y"],
                width=it["width"],
                height=it["height"],
                confidence=it["confidence"],
                strategy=self.name,
            )
            if best is None or el.confidence > best.confidence:
                best = el
        return best


class AIVisionStrategy(FindStrategy):
    """Find element using AI vision (send screenshot to LLM).

    Fallback strategy for complex scenes where control tree / template / OCR fail.
    Only enabled if an LLM endpoint is configured.
    """

    name = "ai_vision"

    def __init__(self, config: dict, controller: Optional["RpaController"] = None):
        super().__init__(config, controller)
        self._enabled = config.get("finder", {}).get("ai_vision_enabled", False)
        self._endpoint = config.get("finder", {}).get("ai_vision_endpoint")
        self._model = config.get("finder", {}).get("ai_vision_model", "gpt-4o")
        self._api_key = config.get("finder", {}).get("ai_vision_api_key")

    def supports(self, target: FindTarget) -> bool:
        return bool(self._enabled and self._endpoint)

    def find(self, screenshot: np.ndarray, target: FindTarget,
             window_offset: tuple[int, int] = (0, 0)) -> Optional[Element]:
        # TODO: implement LLM vision call when an endpoint is configured.
        # This is intentionally left as a stub because it requires a
        # private/external service and the project policy is zero external
        # dependencies by default.
        return None


class ElementFinder:
    """Chained element finder: tries strategies in order until one succeeds."""

    def __init__(
        self,
        strategies: list[FindStrategy],
        config: dict,
        controller: Optional["RpaController"] = None,
    ):
        self._strategies = strategies
        self.config = config
        self.controller = controller

    @classmethod
    def from_config(cls, config: dict, controller: Optional["RpaController"] = None) -> "ElementFinder":
        """Build a finder from config, instantiating the configured strategy chain."""
        chain_names = config.get("finder", {}).get(
            "strategy_chain", ["template_match", "ocr"]
        )
        strategy_map = {
            "control_tree": lambda c, ctrl: ControlTreeStrategy(c, ctrl),
            "template_match": lambda c, ctrl: TemplateMatchStrategy(c, ctrl),
            "ocr": lambda c, ctrl: OCRStrategy(c, ctrl),
            "ai_vision": lambda c, ctrl: AIVisionStrategy(c, ctrl),
        }
        strategies = [
            strategy_map[name](config, controller)
            for name in chain_names
            if name in strategy_map
        ]
        return cls(strategies=strategies, config=config, controller=controller)

    def find(self, screenshot: np.ndarray, target: FindTarget,
             window_offset: tuple[int, int] = (0, 0)) -> Optional[Element]:
        """Try each strategy in chain order. Return first match or None."""
        for strategy in self._strategies:
            if not strategy.supports(target):
                continue
            element = strategy.find(screenshot, target, window_offset)
            if element is not None:
                return element
        return None
