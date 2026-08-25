"""Element Finder - strategy-chain UI element location.

Given a FindTarget (template image / text / region), tries each FindStrategy
in order until one succeeds. This enables graceful degradation:
template matching (fast, precise) -> OCR (medium, dynamic text) -> AI vision (slow, flexible).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

import numpy as np


@dataclass
class FindTarget:
    """Describes what to find on screen.

    Attributes:
        template: relative path to template image (for TemplateMatchStrategy)
        text: text to locate (for OCRStrategy / AIVisionStrategy)
        text_contains: if True, match substring; if False, exact match
        region: (l, t, r, b) to constrain search area within the screenshot
    """
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

    @abstractmethod
    def supports(self, target: FindTarget) -> bool:
        """Whether this strategy can handle the given target."""
        ...

    @abstractmethod
    def find(self, screenshot: np.ndarray, target: FindTarget,
             window_offset: tuple[int, int] = (0, 0)) -> Optional[Element]:
        """Locate the target in the screenshot. Returns Element or None.

        Args:
            screenshot: BGR ndarray of the WeChat window (or region).
            window_offset: (left, top) of the screenshot in screen coords,
                           needed to convert local coords to screen-absolute.
        """
        ...


class TemplateMatchStrategy(FindStrategy):
    """Find element by OpenCV template matching.

    Best for fixed UI icons (search button, send button, etc.).
    Templates are stored in config['rpa']['template_dir'].
    """

    name = "template_match"

    def __init__(self, config: dict):
        self.config = config
        self._template_dir = config.get("rpa", {}).get("template_dir", "./config/templates")
        self._threshold = config.get("rpa", {}).get("template_threshold", 0.8)

    def supports(self, target: FindTarget) -> bool:
        return target.template is not None

    def find(self, screenshot, target, window_offset=(0, 0)):
        """TODO: implement using cv2.matchTemplate.

        Steps:
        1. Load template image from self._template_dir / target.template
        2. cv2.matchTemplate(screenshot, template, TM_CCOEFF_NORMED)
        3. cv2.minMaxLoc -> best match location + score
        4. If score >= self._threshold, return Element with screen-absolute coords
           (add window_offset to match location)
        5. Else return None
        """
        raise NotImplementedError


class OCRStrategy(FindStrategy):
    """Find element by text recognition using EasyOCR.

    Best for dynamic text (contact names, message content).
    """

    name = "ocr"

    def __init__(self, config: dict):
        self.config = config
        self._reader = None  # lazy init

    def _get_reader(self):
        """TODO: lazy-load EasyOCR reader.
        reader = easyocr.Reader(config['rpa']['ocr_languages'], gpu=config['rpa']['ocr_gpu'])
        """
        raise NotImplementedError

    def supports(self, target: FindTarget) -> bool:
        return target.text is not None

    def find(self, screenshot, target, window_offset=(0, 0)):
        """TODO: implement using easyocr.

        Steps:
        1. reader.readtext(screenshot, text_threshold=0.3, low_text=0.3, detail=1)
        2. For each result (bbox, text, conf):
           - If target.text_contains and target.text in text -> match
           - If not text_contains and text == target.text -> match
        3. Return Element with center coords + window_offset
        4. If no match, return None
        """
        raise NotImplementedError


class AIVisionStrategy(FindStrategy):
    """Find element using AI vision (send screenshot to LLM).

    Fallback strategy for complex scenes where template/OCR fail.
    Optional - only enabled if LLM endpoint is configured.
    """

    name = "ai_vision"

    def __init__(self, config: dict):
        self.config = config

    def supports(self, target: FindTarget) -> bool:
        # Supports any target type if AI vision is enabled
        return self.config.get("finder", {}).get("ai_vision_enabled", False)

    def find(self, screenshot, target, window_offset=(0, 0)):
        """TODO: implement by sending screenshot to a vision-capable LLM.
        - Encode screenshot as base64
        - Ask: "Find the element described by {target.text or target.template}, return center x,y"
        - Parse response, return Element
        """
        raise NotImplementedError


class ElementFinder:
    """Chained element finder: tries strategies in order until one succeeds.

    Usage:
        finder = ElementFinder(strategies=[tms, ocr], config=config)
        element = finder.find(screenshot, FindTarget(text="文件传输助手"))
        if element:
            controller.click(element.x, element.y)
    """

    def __init__(self, strategies: list[FindStrategy], config: dict):
        self._strategies = strategies
        self.config = config

    @classmethod
    def from_config(cls, config: dict) -> "ElementFinder":
        """Build a finder from config, instantiating the configured strategy chain."""
        chain_names = config.get("finder", {}).get("strategy_chain", ["template_match", "ocr"])
        strategy_map = {
            "template_match": lambda c: TemplateMatchStrategy(c),
            "ocr": lambda c: OCRStrategy(c),
            "ai_vision": lambda c: AIVisionStrategy(c),
        }
        strategies = [strategy_map[name](config) for name in chain_names if name in strategy_map]
        return cls(strategies=strategies, config=config)

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
