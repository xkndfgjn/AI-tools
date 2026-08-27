"""Window Watcher - background health monitor for the WeChat window.

Runs a periodic check to verify:
- WeChat process is alive
- WeChat window is visible and responsive
- Window is not stuck (optional: compare screenshots)

If anomalies are detected, attempts recovery (re-activate window).
If recovery fails, sets a degraded flag so the API can report it.
"""
from __future__ import annotations

import asyncio
from typing import Callable, Optional


class WindowWatcher:
    """Background monitor for WeChat window health."""

    def __init__(self, controller, config: dict, logger=None):
        self.controller = controller
        self.config = config
        self.logger = logger
        self._check_interval = config.get("watcher", {}).get("interval_seconds", 10)
        self._running = False
        self._degraded = False
        self._last_hash: Optional[int] = None
        self._on_degraded: Optional[Callable] = None

    @property
    def is_degraded(self) -> bool:
        return self._degraded

    async def start(self):
        """Start the periodic check loop."""
        self._running = True
        while self._running:
            try:
                await self._check_once()
            except Exception as e:
                if self.logger:
                    self.logger.warning(f"Watcher check failed: {e}")
                self._degraded = True
            await asyncio.sleep(self._check_interval)

    async def stop(self):
        """Stop the periodic check loop."""
        self._running = False

    async def _check_once(self):
        """Single health check.

        We do *not* activate the window during normal checks to avoid stealing
        focus. Activation is only used during recovery.
        """
        # Find window (sync) in thread pool to avoid blocking the event loop.
        hwnd = await asyncio.to_thread(self.controller.find_wechat_window)
        if not hwnd:
            self._degraded = True
            if self.logger:
                self.logger.warning("Watcher: WeChat window not found")
            await self._recover()
            return

        # Verify we can still get window geometry.
        rect = await asyncio.to_thread(self.controller.get_window_rect)
        if rect is None:
            self._degraded = True
            if self.logger:
                self.logger.warning("Watcher: could not read WeChat window rect")
            await self._recover()
            return

        self._degraded = False

    async def _recover(self):
        """Attempt to recover from a degraded state."""
        try:
            hwnd = await asyncio.to_thread(self.controller.find_wechat_window)
            if hwnd:
                await asyncio.to_thread(self.controller.activate_window)
                if self.logger:
                    self.logger.info("Watcher: recovered WeChat window")
            else:
                if self.logger:
                    self.logger.warning("Watcher: recovery failed - WeChat not found")
        except Exception as e:
            if self.logger:
                self.logger.warning(f"Watcher: recovery error: {e}")

    @staticmethod
    def _image_hash(image) -> int:
        """Fast coarse hash for stuck detection."""
        try:
            import numpy as np
            # Resize to tiny thumbnail and compute mean per channel.
            h, w = image.shape[:2]
            if h > 16 and w > 16:
                thumb = image[::max(1, h // 8), ::max(1, w // 8)]
            else:
                thumb = image
            return int(np.mean(thumb))
        except Exception:
            return 0
