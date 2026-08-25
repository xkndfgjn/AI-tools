"""Window Watcher - background health monitor for the WeChat window.

Runs a periodic check (every N seconds) to verify:
- WeChat process is alive
- WeChat window is visible and responsive
- Window is not stuck (optional: compare screenshots)

If anomalies are detected, attempts recovery (re-activate window).
If recovery fails, sets a degraded flag so the API can report it.
"""
from __future__ import annotations

import asyncio
from typing import Optional, Callable


class WindowWatcher:
    """Background monitor for WeChat window health."""

    def __init__(self, controller, config: dict, logger=None):
        self.controller = controller
        self.config = config
        self.logger = logger
        self._check_interval = 10  # seconds
        self._running = False
        self._degraded = False
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
        """TODO: implement single health check.

        Steps:
        1. Find WeChat window via controller.find_wechat_window()
        2. If not found -> mark degraded, try recovery
        3. If found -> try activate, take a quick screenshot to verify responsiveness
        4. Compare with last screenshot (optional stuck-detection)
        5. Update self._degraded flag
        """
        raise NotImplementedError

    async def _recover(self):
        """TODO: attempt to recover from a degraded state.

        - Re-find the WeChat window
        - Re-activate it
        - If process died, log and wait for user to restart WeChat
        """
        raise NotImplementedError
