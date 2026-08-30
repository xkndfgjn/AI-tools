"""Clean and cluster raw OCR blocks from a WeChat chat region.

Qt WeChat exposes no control tree, so ``read_messages`` OCRs the chat area
and gets back a flat list of text boxes. That raw list mixes:

- real chat messages (what we want)
- time separators ("16:11", "昨天18:20", "星期一", "2026/8/27")
- the folded "聊天记录" preview card: a title ("XX的聊天记录"), a bottom
  label ("聊天记录" / "查看更多聊天记录"), and between them a few
  sender-prefixed history rows ("Luclui: ...") that are NOT live messages
- single-glyph noise misread off avatars / icons (tall, narrow box)

This module turns that soup into a clean ordered list of current-session
messages. It is pure (no I/O, no OCR) so it can be unit-tested directly
against a dumped OCR fixture (see tests/fixtures/ocr_mama_chat.json).

Public API:
    parse_messages(items) -> (messages, stats)

    messages: [{content, confidence, time}]  ordered top->bottom, current session only.
               ``time`` is the most recent timestamp separator seen above the
               message (e.g. "16:11", "昨天18:20"), or None when messages
               appear before any separator in the chat.
    stats:     {message, time, system, history, noise}  counts of each kind
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

# A parsed OCR item needs at least these fields.
# (OcrEngine.extract / _helpers.ocr_extract_text already provide them.)
#   text, confidence, box (4 [[x,y]]), center_x, center_y, width, height


# --- classifiers ---------------------------------------------------------

# Pure clock times: 16:11, 17：24, 09:05
_TIME_RE = re.compile(r"^\d{1,2}[:：]\d{2}$")
# Yesterday/today/today + time: 昨天18:20, 今天 09:05
_RELTIME_RE = re.compile(r"^(昨天|前天|今天)\s*\d{1,2}[:：]\d{2}$")
# Weekday: 星期一, 周日, 星期天
_WEEKDAY_RE = re.compile(r"^(星期|周)[一二三四五六日天]$")
# Full date, optional with time: 2026/8/27, 2026-08-27 14:00
_DATE_RE = re.compile(r"^\d{4}[/-]\d{1,2}[/-]\d{1,2}(\s*\d{1,2}[:：]\d{2})?$")
# Period + time: 上午 09:05, 下午3：00
_PERIOD_RE = re.compile(r"^(上午|中午|下午|晚上)\s*\d{1,2}[:：]\d{2}$")

_SYSTEM_KEYWORDS = (
    "以下是新消息", "以下为新消息", "以上为新消息", "以上是打招呼",
    "撤回了一条消息", "你撤回了", "对方撤回", "已读",
)
# History-preview rows like "Luclui: xxx" / "张三：你好".
# A live message almost never starts with "Name:" - that prefix only appears
# inside the folded 聊天记录 card preview.
_SENDER_PREFIX_RE = re.compile(r"^[^\s:：]{1,20}[:：]\s*\S")


def is_timestamp(text: str) -> bool:
    t = text.strip()
    return any(r.match(t) for r in (_TIME_RE, _RELTIME_RE, _WEEKDAY_RE, _DATE_RE, _PERIOD_RE))


def is_system_notice(text: str) -> bool:
    t = text.strip()
    return any(k in t for k in _SYSTEM_KEYWORDS)


def is_chat_history_marker(text: str) -> bool:
    """Title ('XX的聊天记录') or bottom label ('聊天记录' / '查看更多聊天记录')."""
    return "聊天记录" in text.strip()


def is_sender_prefixed(text: str) -> bool:
    return bool(_SENDER_PREFIX_RE.match(text.strip()))


# --- geometry helpers ----------------------------------------------------

def _x_interval(item: dict) -> Tuple[float, float]:
    box = item["box"]
    xs = [p[0] for p in box]
    return (min(xs), max(xs))


def _merge_multiline(items: List[dict]) -> List[dict]:
    """Merge OCR blocks that belong to the same message bubble.

    Two blocks merge when, going top->bottom, their vertical centers are
    close (within ~0.6 of their combined height) AND their x-intervals
    overlap (same horizontal band, i.e. same bubble). This stitches a
    message that OCR split across two lines (e.g. a long filename) back
    into one entry.
    """
    if not items:
        return []
    items = sorted(items, key=lambda i: i["center_y"])
    merged = [{**items[0], "_parts": [items[0]["text"]]}]
    for cur in items[1:]:
        prev = merged[-1]
        y_gap = abs(cur["center_y"] - prev["center_y"])
        y_thresh = 0.6 * (prev["height"] + cur["height"])
        y_close = y_gap <= y_thresh
        p_l, p_r = _x_interval(prev)
        c_l, c_r = _x_interval(cur)
        x_overlap = not (c_r < p_l or c_l > p_r)
        if y_close and x_overlap:
            prev["_parts"].append(cur["text"])
            xs = [p[0] for p in prev["box"]] + [p[0] for p in cur["box"]]
            ys = [p[1] for p in prev["box"]] + [p[1] for p in cur["box"]]
            prev["center_y"] = int(sum(ys) / len(ys))
            prev["center_x"] = int(sum(xs) / len(xs))
            prev["width"] = int(max(xs) - min(xs))
            prev["height"] = int(max(ys) - min(ys))
            prev["confidence"] = min(prev["confidence"], cur["confidence"])
            prev["box"] = [[min(xs), min(ys)], [max(xs), min(ys)],
                           [max(xs), max(ys)], [min(xs), max(ys)]]
        else:
            merged.append({**cur, "_parts": [cur["text"]]})
    for m in merged:
        m["text"] = "\n".join(m.pop("_parts"))
    return merged


# --- main entry ----------------------------------------------------------

def parse_messages(items: List[dict]) -> Tuple[List[dict], dict]:
    """Clean raw OCR blocks into current-session messages.

    Args:
        items: OCR items with text/confidence/box/center_x/center_y/width/height.

    Returns:
        (messages, stats)
        messages: [{content, confidence, time}] top->bottom, live messages only.
                   time = most recent timestamp separator above the message,
                   or None before the first separator.
        stats:    {message, time, system, history, noise} per-kind counts.
    """
    stats = {"message": 0, "time": 0, "system": 0, "history": 0, "noise": 0}
    clean = [it for it in items if (it.get("text") or "").strip()]

    # Classify each block, tracking the folded 聊天记录 card span and the
    # most recent timestamp separator. The card runs from a title
    # ('XX的聊天记录') to the next bare label ('聊天记录' /
    # '查看更多聊天记录'); everything inside is history, not a live message.
    # A time separator also closes the card (it starts a fresh live section)
    # and is remembered so the live messages that follow it carry that
    # timestamp. 'Name: ...' rows are history even without a detected card,
    # since that prefix only appears in the card preview.
    in_card = False
    current_time: Optional[str] = None
    final: List[Tuple[dict, str]] = []
    msg_blocks: List[dict] = []
    for it in clean:
        t = (it["text"] or "").strip()
        if is_timestamp(t):
            kind = "time"
            current_time = t  # stamp applies to all following live messages
            in_card = False  # a time separator starts a fresh live section
        elif is_system_notice(t):
            kind = "system"
        elif is_chat_history_marker(t):
            kind = "history"
            in_card = "的聊天记录" in t  # title opens, bare label closes
        elif in_card:
            kind = "history"
        elif is_sender_prefixed(t):
            kind = "history"
        else:
            kind = "message"
            msg_blocks.append({**it, "_time": current_time})
        final.append((it, kind))

    # Pass 3: merge multi-line live messages, then drop single-glyph noise.
    # _merge_multiline shallow-copies each block, so the ``_time`` tag we
    # attached above rides along; a merged bubble keeps the first block's
    # time, which is correct since a timestamp separator never sits inside
    # one bubble.
    merged = _merge_multiline(msg_blocks)
    # Average line height from non-single-glyph blocks only, so a tall noise
    # box doesn't drag the average up and mask itself.
    non_single = [it["height"] for it, _ in final if len((it["text"] or "").strip()) > 1]
    avg_h = (sum(non_single) / len(non_single)) if non_single else 1.0

    messages: List[dict] = []
    for m in merged:
        content = m["text"].strip()
        if len(content) <= 1 and m["height"] > 2 * avg_h:
            stats["noise"] += 1
            continue
        messages.append({
            "content": content,
            "confidence": round(float(m["confidence"]), 3),
            "time": m.get("_time"),
        })
        stats["message"] += 1

    for _, kind in final:
        if kind != "message":
            stats[kind] = stats.get(kind, 0) + 1

    return messages, stats
