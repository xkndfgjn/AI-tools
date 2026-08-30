"""read_messages cleaning tests.

The parser (src/operations/_message_parser.py) is pure, so we test it
directly against:
  - a real dumped OCR fixture from the '老妈' chat (13 blocks, see HANDOFF)
  - synthetic blocks for multiline-merge and timestamp/history filtering

The fixture (tests/fixtures/ocr_mama_chat.json) was produced by
`python scripts/dump_ocr.py <png> chat` against a real post-execution
screenshot, then cropped to the chat_region. It captures exactly the noise
the cleaner must handle: time separators, a folded 聊天记录 card, and a
single-glyph avatar misread.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from src.operations._message_parser import (
    parse_messages,
    is_timestamp,
    is_sender_prefixed,
    is_chat_history_marker,
)

FIXTURE = Path(__file__).parent / "fixtures" / "ocr_mama_chat.json"


def _load_fixture():
    """Load dumped OCR blocks and map dump field names -> parser field names."""
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return [
        {
            "text": r["text"],
            "confidence": r["conf"],
            "box": r["box"],
            "center_x": r["cx"],
            "center_y": r["cy"],
            "width": r["w"],
            "height": r["h"],
        }
        for r in raw
    ]


skip_no_fixture = pytest.mark.skipif(
    not FIXTURE.exists(), reason="OCR fixture not present"
)


def _block(text, cx, cy, w, h, conf=0.99):
    """Build an axis-aligned OCR block for synthetic tests."""
    x0, y0 = cx - w // 2, cy - h // 2
    x1, y1 = cx + w // 2, cy + h // 2
    return {
        "text": text,
        "confidence": conf,
        "box": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]],
        "center_x": cx,
        "center_y": cy,
        "width": w,
        "height": h,
    }


# --- classifiers ---------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("16:11", True),
    ("17：24", True),
    ("昨天18:20", True),
    ("今天 09:05", True),
    ("星期一", True),
    ("周日", True),
    ("2026/8/27", True),
    ("2026-08-27 14:00", True),
    ("下午3：00", True),
    ("老妈你回不回来吃饭", False),
    ("回来", False),
    ("Luclui的聊天记录", False),
    ("发送消息测试", False),
])
def test_is_timestamp(text, expected):
    assert is_timestamp(text) is expected


def test_is_sender_prefixed():
    assert is_sender_prefixed("Luclui: 这个便宜一点 https://mojie.app/")
    assert is_sender_prefixed("张三：你好")
    assert not is_sender_prefixed("老妈你回不回来吃饭")
    assert not is_sender_prefixed("回来")


def test_is_chat_history_marker():
    assert is_chat_history_marker("Luclui的聊天记录")
    assert is_chat_history_marker("聊天记录")
    assert is_chat_history_marker("查看更多聊天记录")
    assert not is_chat_history_marker("发送消息测试")


# --- real fixture --------------------------------------------------------

@skip_no_fixture
def test_parse_real_mama_chat_fixture():
    items = _load_fixture()
    messages, stats = parse_messages(items)

    # Only the 3 live messages survive, each carrying the timestamp that
    # preceded it in the chat.
    assert messages == [
        {"content": "老妈你回不回来吃饭", "confidence": 1.0, "time": "16:11"},
        {"content": "回来", "confidence": 1.0, "time": "16:11"},
        {"content": "发送消息测试", "confidence": 1.0, "time": "17:24"},
    ]

    # Filtering breakdown matches the known fixture composition.
    assert stats["message"] == 3
    assert stats["time"] == 3          # 昨天18:20, 16:11, 17:24
    assert stats["history"] == 6       # card title, 4 rows, card label
    assert stats["noise"] == 1         # '福' (single glyph, tall box)
    assert stats["system"] == 0


# --- multiline merge -----------------------------------------------------

def test_sender_prefixed_row_outside_card_is_history():
    # A 'Name: ...' row is a folded-card preview even with no card title
    # detected; it must never leak through as a live message.
    row = _block("Luclui: 这个便宜一点 https://mojie.app/", cx=219, cy=150, w=280, h=22)
    messages, stats = parse_messages([row])
    assert messages == []
    assert stats["history"] == 1


def test_merges_multiline_live_message():
    # Two plain lines close in y, overlapping in x -> one message.
    top = _block("第一行内容", cx=200, cy=300, w=160, h=22)
    bot = _block("第二行续", cx=210, cy=320, w=150, h=22)
    messages, stats = parse_messages([top, bot])

    assert len(messages) == 1
    assert "第一行内容" in messages[0]["content"]
    assert "第二行续" in messages[0]["content"]
    assert stats["message"] == 1


def test_does_not_merge_separate_messages():
    # Two clearly separate bubbles (big y gap) stay as two messages.
    a = _block("你好", cx=200, cy=300, w=80, h=22)
    b = _block("在吗", cx=200, cy=400, w=80, h=22)
    messages, stats = parse_messages([a, b])
    assert len(messages) == 2
    assert stats["message"] == 2


# --- noise / history filtering -------------------------------------------

def test_filters_single_glyph_tall_noise():
    # '福'-like avatar misread: 1 char, height far above average.
    noise = _block("福", cx=415, cy=75, w=55, h=57, conf=0.93)
    real = _block("发送消息测试", cx=309, cy=506, w=110, h=22)
    messages, stats = parse_messages([noise, real])
    assert [m["content"] for m in messages] == ["发送消息测试"]
    assert stats["noise"] == 1
    assert stats["message"] == 1


def test_keeps_two_char_message():
    # '回来' is only 2 chars but normal height -> must NOT be dropped.
    msg = _block("回来", cx=112, cy=385, w=45, h=26)
    messages, stats = parse_messages([msg])
    assert [m["content"] for m in messages] == ["回来"]
    assert stats["message"] == 1
    assert stats["noise"] == 0


def test_filters_chat_history_card_span():
    # A full card: title, two sender-prefixed rows, a continuation line, label.
    blocks = [
        _block("Luclui的聊天记录", cx=149, cy=81, w=141, h=23),
        _block("Luclui: [文件] FlClash-0.8.91-windows-", cx=217, cy=109, w=274, h=19),
        _block("amd64-setup.exe", cx=144, cy=130, w=127, h=17),
        _block("聊天记录", cx=112, cy=200, w=66, h=20),
        # live message after the card
        _block("老妈你回不回来吃饭", cx=282, cy=314, w=161, h=21),
    ]
    messages, stats = parse_messages(blocks)
    assert [m["content"] for m in messages] == ["老妈你回不回来吃饭"]
    assert stats["history"] == 4
    assert stats["message"] == 1


def test_empty_input():
    messages, stats = parse_messages([])
    assert messages == []
    assert stats == {"message": 0, "time": 0, "system": 0, "history": 0, "noise": 0}


# --- timestamp carry-through --------------------------------------------

def test_message_carries_preceding_timestamp():
    # Each timestamp separator stamps every live message that follows it,
    # until the next separator.
    blocks = [
        _block("16:11", cx=228, cy=100, w=43, h=19),
        _block("在吗", cx=200, cy=150, w=80, h=22),
        _block("17:24", cx=228, cy=250, w=44, h=19),
        _block("回来了", cx=200, cy=300, w=90, h=22),
    ]
    messages, stats = parse_messages(blocks)
    assert [m["content"] for m in messages] == ["在吗", "回来了"]
    assert messages[0]["time"] == "16:11"
    assert messages[1]["time"] == "17:24"
    assert stats["time"] == 2
    assert stats["message"] == 2


def test_message_before_any_timestamp_has_null_time():
    # Messages at the very top of the chat (no separator above them) get
    # time=None rather than inventing one.
    blocks = [_block("你好", cx=200, cy=100, w=80, h=22)]
    messages, stats = parse_messages(blocks)
    assert messages == [{"content": "你好", "confidence": 0.99, "time": None}]
    assert stats["message"] == 1
    assert stats["time"] == 0


def test_timestamp_survives_history_card_for_following_message():
    # A timestamp above a folded 聊天记录 card still applies to the live
    # message that appears after the card closes.
    blocks = [
        _block("16:11", cx=228, cy=50, w=43, h=19),
        _block("Luclui的聊天记录", cx=149, cy=100, w=141, h=23),
        _block("Luclui: 你好", cx=217, cy=130, w=150, h=19),
        _block("聊天记录", cx=112, cy=160, w=66, h=20),
        _block("在吗", cx=200, cy=220, w=80, h=22),
    ]
    messages, stats = parse_messages(blocks)
    assert [m["content"] for m in messages] == ["在吗"]
    assert messages[0]["time"] == "16:11"


def test_merged_multiline_bubble_keeps_first_block_time():
    # A message OCR-split across two lines inherits the timestamp in force
    # at the bubble, not a later one.
    top = _block("第一行内容", cx=200, cy=300, w=160, h=22)
    bot = _block("第二行续", cx=210, cy=320, w=150, h=22)
    blocks = [
        _block("16:11", cx=228, cy=250, w=43, h=19),
        top,
        bot,
    ]
    messages, stats = parse_messages(blocks)
    assert len(messages) == 1
    assert messages[0]["time"] == "16:11"
    assert stats["message"] == 1
    assert stats["time"] == 1
