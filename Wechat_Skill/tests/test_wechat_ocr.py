"""Tests for the WeChat native OCR backend (src/rpa/wechat_ocr.py).

These cover the pure logic (result normalization, version sorting). The real
wxocr.dll path / sub-process are environment-dependent and are exercised in
live validation, not unit tests.
"""
import pytest

from src.rpa.wechat_ocr import WeChatOcrBackend, _version_key


class TestVersionKey:
    def test_numeric_sort(self):
        assert _version_key("8092") > _version_key("8011")
        assert _version_key("4.1.12.55") > _version_key("4.0.0.26")

    def test_no_digits(self):
        assert _version_key("extracted") == (0,)
        assert _version_key("extracted") < _version_key("8092")


class TestNormalize:
    def test_valid_block(self):
        raw = {
            "imgpath": "x.png", "errcode": 0, "width": 100, "height": 50,
            "ocr_response": [
                {"text": "文件传输助手", "left": 10.0, "top": 20.0,
                 "right": 60.0, "bottom": 40.0, "rate": 0.99},
            ],
        }
        items = WeChatOcrBackend._normalize(raw)
        assert len(items) == 1
        it = items[0]
        assert it["text"] == "文件传输助手"
        assert it["confidence"] == pytest.approx(0.99)
        assert it["center_x"] == 35
        assert it["center_y"] == 30
        assert it["width"] == 50
        assert it["height"] == 20
        assert it["box"] == [[10.0, 20.0], [60.0, 20.0], [60.0, 40.0], [10.0, 40.0]]

    def test_errcode_nonzero_returns_empty(self):
        raw = {"errcode": 1, "ocr_response": [{"text": "x", "left": 0, "top": 0,
                                               "right": 1, "bottom": 1, "rate": 1.0}]}
        assert WeChatOcrBackend._normalize(raw) == []

    def test_empty_response(self):
        assert WeChatOcrBackend._normalize({"errcode": 0, "ocr_response": []}) == []

    def test_not_dict(self):
        assert WeChatOcrBackend._normalize(None) == []
        assert WeChatOcrBackend._normalize("json string") == []

    def test_blank_text_skipped(self):
        raw = {"errcode": 0, "ocr_response": [
            {"text": "  ", "left": 0, "top": 0, "right": 5, "bottom": 5, "rate": 1.0},
            {"text": "ok", "left": 1, "top": 1, "right": 3, "bottom": 3, "rate": 0.9},
        ]}
        items = WeChatOcrBackend._normalize(raw)
        assert len(items) == 1
        assert items[0]["text"] == "ok"

    def test_bad_coords_tolerated(self):
        raw = {"errcode": 0, "ocr_response": [
            {"text": "bad", "left": "x", "top": 0, "right": 5, "bottom": 5, "rate": 1.0},
            {"text": "reversed", "left": 10, "top": 10, "right": 5, "bottom": 20, "rate": 1.0},
        ]}
        assert WeChatOcrBackend._normalize(raw) == []
