"""Shared helpers for WeChat operations.

OCR is provided by the shared RapidOCR singleton (src.rpa.ocr_engine).
Control-tree based location has been removed: Qt-rendered WeChat exposes
no UIAutomation control tree, so all element location is vision-based
(OCR + templates).
"""
from __future__ import annotations

import asyncio
from typing import Optional, Tuple

from src.rpa.ocr_engine import OcrEngine


async def sleep_ms(ctx, ms: Optional[int] = None) -> None:
    """Non-blocking sleep using config['rpa']['action_delay_ms']."""
    ms = ms or ctx.config.get("rpa", {}).get("action_delay_ms", 300)
    await asyncio.sleep(ms / 1000.0)


async def open_chat(ctx, name: str) -> Tuple[bool, str]:
    """Open the chat window for a contact/group by name.

    Pure-vision flow (no control tree):
      1. Activate WeChat
      2. Ctrl+F -> clear -> type the name
      3. Wait for the search panel to refresh
      4. OCR the search-results region (excludes the top search box)
      5. Pick the topmost candidate that matches the name
      6. Click it

    Region geometry is config-driven (config['search']) so it can be tuned
    per WeChat version without code changes. Use GET /api/debug/ocr after a
    Ctrl+F to calibrate.
    """
    controller = ctx.controller

    activated = await asyncio.to_thread(controller.activate_window)
    if not activated:
        return False, "WeChat window not found"

    # Open search, clear any previous query, type the name.
    await asyncio.to_thread(controller.press_keys, "Ctrl", "f")
    await sleep_ms(ctx, 300)
    await asyncio.to_thread(controller.press_keys, "Ctrl", "a")
    await asyncio.to_thread(controller.type_text, name)

    s_cfg = ctx.config.get("search", {})
    await sleep_ms(ctx, s_cfg.get("settle_ms", 1200))

    rect = controller.get_window_rect()
    if rect is None:
        return False, "No window rect"

    left, top, right, bottom = rect
    width = right - left

    # Search-results region (window-relative), skipping the top search box.
    box_h = int(s_cfg.get("box_height_px", 90))
    res_left = 0
    res_top = box_h
    res_right = int(width * float(s_cfg.get("result_width_ratio", 0.40)))
    res_bottom = min(int(s_cfg.get("result_height_px", 600)), bottom - top)
    if res_bottom <= res_top or res_right <= res_left:
        return False, "Search region too small (window smaller than configured box)"

    screenshot = await asyncio.to_thread(controller.screenshot, rect)
    roi = screenshot[res_top:res_bottom, res_left:res_right]

    engine = OcrEngine.get(ctx.config)
    items = await asyncio.to_thread(engine.extract, roi)

    candidates = []
    for it in items:
        text = (it["text"] or "").strip()
        if not text:
            continue
        # Bidirectional substring match tolerates OCR noise on either side.
        if name in text or text in name:
            candidates.append({
                "x": left + res_left + it["center_x"],
                "y": top + res_top + it["center_y"],
                "confidence": it["confidence"],
                "text": text,
            })

    if not candidates:
        return False, f"Cannot find '{name}' in search results"

    # WeChat's Ctrl+F panel lists, top to bottom:
    #   - "搜一搜" suggestions (e.g. "文件传输助手打开", "...怎么恢复历史记录")
    #   - the actual contact/group match (the bare name)
    #   - chat-record rows ("...与<name>的聊天记录")
    # The topmost hit is usually a 搜一搜 suggestion, NOT the contact. So we
    # prefer an EXACT name match; otherwise fall back to the SHORTEST text
    # (contact names are short; suggestions/records are long phrases).
    exact = [c for c in candidates if c["text"] == name]
    if exact:
        exact.sort(key=lambda c: c["y"])
        best = exact[0]
    else:
        candidates.sort(key=lambda c: (len(c["text"]), c["y"]))
        best = candidates[0]
    await asyncio.to_thread(controller.click, best["x"], best["y"])
    await sleep_ms(ctx, 500)
    return True, f"Opened '{best['text']}' (conf {best['confidence']:.2f})"


async def estimate_chat_region(ctx) -> Optional[Tuple[int, int, int, int]]:
    """Estimate the chat message area within the WeChat window.

    Qt WeChat exposes no useful child controls, so the region is anchored by
    configurable window proportions. The defaults exclude the left session
    list, title bar, and bottom input box.
    """
    controller = ctx.controller
    rect = controller.get_window_rect()
    if rect is None:
        return None
    left, top, right, bottom = rect
    width = right - left
    height = bottom - top
    cfg = ctx.config.get("chat_region", {})

    left_ratio = float(cfg.get("left_ratio", 0.45))
    top_ratio = float(cfg.get("top_ratio", 0.12))
    right_ratio = float(cfg.get("right_ratio", 0.99))
    bottom_ratio = float(cfg.get("bottom_ratio", 0.79))

    chat_left = left + int(width * left_ratio)
    chat_top = top + int(height * top_ratio)
    chat_right = left + int(width * right_ratio)
    chat_bottom = top + int(height * bottom_ratio)

    chat_left = max(left, min(chat_left, right - 50))
    chat_top = max(top, min(chat_top, bottom - 50))
    chat_right = max(chat_left + 50, min(chat_right, right))
    chat_bottom = max(chat_top + 50, min(chat_bottom, bottom))
    return (chat_left, chat_top, chat_right, chat_bottom)


async def ocr_extract_text(image, ctx) -> list[dict]:
    """Extract all text from an image via the shared RapidOCR engine.

    Returns [{text, confidence, center_x, center_y}].
    """
    items = OcrEngine.get(ctx.config).extract(image)
    return [
        {
            "text": it["text"],
            "confidence": it["confidence"],
            "center_x": it["center_x"],
            "center_y": it["center_y"],
        }
        for it in items
    ]
