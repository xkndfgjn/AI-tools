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
    - pre_hook(): pre-execution actions (default: screenshot)
    - post_hook(): post-execution actions (default: screenshot + attach to result)
    - Set requires_confirmation = True for human-in-the-loop operations
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

    async def pre_hook(self, ctx: OperationContext, params: dict) -> None:
        """Default: capture pre-execution screenshot for audit.

        Override to add validation, human confirmation checks, etc.
        """
        try:
            path = ctx.controller.save_screenshot()
            if path:
                ctx.screenshots.append(path)
        except Exception as e:
            ctx.logger.debug(f"pre_hook screenshot skipped: {e}")

    async def post_hook(self, ctx: OperationContext, params: dict,
                        result: OperationResult) -> None:
        """Default: capture post-execution screenshot for audit.

        Override to add result verification, logging, etc.
        """
        try:
            path = ctx.controller.save_screenshot()
            if path:
                ctx.screenshots.append(path)
        except Exception as e:
            ctx.logger.debug(f"post_hook screenshot skipped: {e}")
