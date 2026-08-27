"""open_chat logic test - verifies the OCR -> candidate -> click chain
without a live WeChat. Uses the real OcrEngine (RapidOCR) on a synthetic
image, mocking only the controller IO.

Covers the first milestone: opening a named contact's chat window.
"""
import asyncio
import os
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from src.operations._helpers import open_chat
from src.rpa.ocr_engine import OcrEngine

FONT = "C:/Windows/Fonts/msyh.ttc"
skip_no_font = pytest.mark.skipif(
    not os.path.exists(FONT), reason="CJK font not available on this machine"
)

CONFIG = {
    "rpa": {"action_delay_ms": 0},
    "search": {
        "box_height_px": 90,
        "result_width_ratio": 0.40,
        "result_height_px": 600,
        "settle_ms": 0,
    },
}


@dataclass
class OperationContext:
    controller: object
    finder: object
    config: dict
    logger: object = None
    screenshots: list | None = None

    def __post_init__(self):
        if self.screenshots is None:
            self.screenshots = []


class FakeController:
    """Mimics RpaController IO; returns a fixed synthetic screenshot."""

    def __init__(self, image: np.ndarray, rect):
        self._image = image
        self.rect = rect
        self.clicked = []
        self.keys_pressed = []
        self.typed = []

    def activate_window(self):
        return True

    def press_keys(self, *keys):
        self.keys_pressed.append(keys)

    def type_text(self, text):
        self.typed.append(text)

    def get_window_rect(self):
        return self.rect

    def screenshot(self, region=None):
        return self._image

    def click(self, x, y):
        self.clicked.append((x, y))


def _make_image(text: str) -> np.ndarray:
    img = Image.new("RGB", (800, 600), "white")
    d = ImageDraw.Draw(img)
    d.text((20, 120), text, fill="black", font=ImageFont.truetype(FONT, 32))
    return np.array(img)[:, :, ::-1].copy()  # RGB -> BGR


def _ctx(controller):
    return OperationContext(controller=controller, finder=None, config=CONFIG)


@skip_no_font
def test_open_chat_finds_and_clicks_contact():
    img = _make_image("文件传输助手")
    ctrl = FakeController(img, rect=(0, 0, 800, 600))

    ok, msg = asyncio.run(open_chat(_ctx(ctrl), "文件传输助手"))

    assert ok, msg
    assert ctrl.typed == ["文件传输助手"]
    assert ("Ctrl", "f") in ctrl.keys_pressed
    assert ("Ctrl", "a") in ctrl.keys_pressed
    assert len(ctrl.clicked) == 1

    # The click must land inside the configured search-results region:
    # left strip x in [0, 320], y in [90, 600].
    x, y = ctrl.clicked[0]
    assert 0 <= x <= 320, f"click x={x} outside left strip"
    assert 90 <= y <= 600, f"click y={y} outside results strip"


@skip_no_font
def test_open_chat_missing_contact_returns_failure():
    img = _make_image("张三")
    ctrl = FakeController(img, rect=(0, 0, 800, 600))

    ok, msg = asyncio.run(open_chat(_ctx(ctrl), "不存在的联系人"))

    assert not ok
    assert "Cannot find" in msg
    assert ctrl.clicked == []
