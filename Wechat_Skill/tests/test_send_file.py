"""Unit tests for the visual send_file flow."""
import asyncio
import numpy as np

import src.operations.send_file as send_file_module
from src.operations.base import OperationContext, OperationStatus


class FakeController:
    def __init__(self):
        self.activated = 0
        self.clicked = []
        self.typed = []
        self.keys_pressed = []

    def activate_window(self):
        self.activated += 1
        return True

    def get_window_rect(self):
        return (100, 200, 1100, 1000)

    def click(self, x, y):
        self.clicked.append((x, y))

    def type_text(self, text):
        self.typed.append(text)

    def press_keys(self, *keys):
        self.keys_pressed.append(keys)

    def screenshot(self, region=None):
        return np.zeros((100, 100, 3), dtype=np.uint8)


def _ctx(controller, config=None):
    return OperationContext(
        controller=controller,
        finder=None,
        config=config or {
            "rpa": {"action_delay_ms": 0},
            "chat_region": {},
            "send_file": {"file_button": {"feature_model": "wechat_file_button_features.npz"}},
        },
    )


def test_send_file_uses_template_match_coordinates(tmp_path, monkeypatch):
    file_path = tmp_path / "sample.jpg"
    file_path.write_bytes(b"test")
    controller = FakeController()
    monkeypatch.setattr(send_file_module, "open_chat", _async_true)
    monkeypatch.setattr(
        send_file_module,
        "_find_file_button_by_template",
        lambda ctx, rect, config: (620, 640, 0.98),
    )

    result = asyncio.run(send_file_module.SendFileOperation().execute(
        _ctx(controller), {"to": "文件传输助手", "file_path": str(file_path)}
    ))

    assert result.status == OperationStatus.SUCCESS
    assert controller.activated == 1
    assert controller.clicked == [(620, 640)]
    assert controller.typed == [str(file_path.resolve())]
    assert controller.keys_pressed == [("Enter",), ("Enter",)]


def test_send_file_does_not_click_when_template_is_missing(tmp_path, monkeypatch):
    file_path = tmp_path / "sample.jpg"
    file_path.write_bytes(b"test")
    controller = FakeController()
    monkeypatch.setattr(send_file_module, "open_chat", _async_true)
    monkeypatch.setattr(
        send_file_module,
        "_find_file_button_by_template",
        lambda ctx, rect, config: None,
    )

    result = asyncio.run(send_file_module.SendFileOperation().execute(
        _ctx(controller), {"to": "文件传输助手", "file_path": str(file_path)}
    ))

    assert result.status == OperationStatus.FAILED
    assert "template was not found" in result.message
    assert controller.clicked == []
    assert controller.typed == []
    assert controller.keys_pressed == []


def test_send_file_missing_file_fails_without_ui_actions(tmp_path):
    controller = FakeController()
    result = asyncio.run(send_file_module.SendFileOperation().execute(
        _ctx(controller), {"to": "文件传输助手", "file_path": str(tmp_path / "missing.jpg")}
    ))

    assert result.status == OperationStatus.FAILED
    assert "File not found" in result.message
    assert controller.activated == 0


async def _async_true(ctx, name):
    return True, f"Opened '{name}'"
