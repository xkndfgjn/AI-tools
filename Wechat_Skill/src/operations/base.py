"""Base classes for the Operation Layer.

Defines the contract every WeChat operation must follow:
- BaseOperation: abstract base with execute(), pre_hook(), post_hook()
- OperationContext: carries RPA engine + config + logger to each operation
- OperationResult: standardized return value
- OperationStatus: success / failed / needs_confirmation
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from loguru import logger as _default_logger


class OperationStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    NEEDS_CONFIRMATION = "needs_confirmation"


@dataclass
class OperationResult:
    """Standardized return value from any operation."""
    status: OperationStatus
    data: Any = None
    message: str = ""
    screenshots: list[str] = field(default_factory=list)
    duration_ms: int = 0


@dataclass
class OperationContext:
    """Carries everything an operation needs to do its job.

    Passed to every operation's execute() method.
    """
    controller: Any          # RpaController instance
    finder: Any              # ElementFinder instance
    config: dict             # loaded config (config.yaml)
    logger: Any = _default_logger
    screenshots: list = field(default_factory=list)  # screenshot file paths captured during this operation


class BaseOperation(ABC):
    """Abstract base class for all WeChat operations.

    Subclasses must:
    1. Set `name` and `description` class attributes
    2. Implement `execute(ctx, params) -> OperationResult`

    Optionally override:
    - pre_hook(): pre-execution actions (default: screenshot per audit policy)
    - post_hook(): post-execution actions (default: screenshot per audit policy + attach to result)
    - Set requires_confirmation = True for human-in-the-loop operations

    Audit screenshot policy is config-driven via ``rpa.audit_screenshot``:
      - "on_fail" (default): capture only after a FAILED operation; the pre-state
        is skipped because the post-failure screenshot is what you need to debug.
      - "always": capture before and after every operation.
      - "off": never capture for audit (OCR/template screenshots taken inside
        execute() stay in memory only, never written to disk).
    Old screenshots are pruned to ``rpa.screenshot_retention`` (default 50).
    """

    name: str = "base"
    description: str = ""
    requires_confirmation: bool = False

    async def run(self, ctx: OperationContext, params: dict) -> OperationResult:
        """Full lifecycle: pre_hook -> execute -> post_hook.

        Do NOT override this. Override execute() instead.
        """
        start = time.monotonic()

        # Pre-hook
        await self.pre_hook(ctx, params)

        # Execute
        result = await self.execute(ctx, params)

        # Post-hook
        await self.post_hook(ctx, params, result)

        # Attach timing
        result.duration_ms = int((time.monotonic() - start) * 1000)

        # Attach screenshots captured during execution
        if ctx.screenshots:
            result.screenshots = ctx.screenshots

        return result

    @abstractmethod
    async def execute(self, ctx: OperationContext, params: dict) -> OperationResult:
        """Core logic. Implement in subclass.

        Args:
            ctx: OperationContext with controller, finder, config, logger
            params: operation-specific parameters (e.g., {"to": "...", "text": "..."})

        Returns:
            OperationResult with status, data, message
        """
        ...

    def _audit_policy(self, ctx: OperationContext) -> str:
        """Return the audit screenshot policy: 'on_fail' | 'always' | 'off'."""
        return str(ctx.config.get("rpa", {}).get("audit_screenshot", "on_fail")).lower()

    async def pre_hook(self, ctx: OperationContext, params: dict) -> None:
        """Capture pre-execution screenshot only when policy is 'always'.

        'on_fail' deliberately skips the pre-shot: the post-failure screenshot
        is sufficient for debugging, and skipping halves the disk writes for
        the common (success) path.
        """
        if self._audit_policy(ctx) != "always":
            return
        try:
            path = ctx.controller.save_screenshot()
            if path:
                ctx.screenshots.append(path)
        except Exception as e:
            ctx.logger.debug(f"pre_hook screenshot skipped: {e}")

    async def post_hook(self, ctx: OperationContext, params: dict,
                        result: OperationResult) -> None:
        """Capture post-execution screenshot per audit policy.

        - 'always': always capture.
        - 'on_fail': capture only when the operation FAILED (the valuable case
          for debugging; success path writes nothing).
        - 'off': never capture.
        """
        policy = self._audit_policy(ctx)
        if policy == "off":
            return
        if policy == "on_fail" and result.status != OperationStatus.FAILED:
            return
        try:
            path = ctx.controller.save_screenshot()
            if path:
                ctx.screenshots.append(path)
        except Exception as e:
            ctx.logger.debug(f"post_hook screenshot skipped: {e}")
