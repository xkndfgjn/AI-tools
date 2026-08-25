"""FastAPI route definitions.

All routes delegate to the Operation Layer or RPA Engine Layer.
No RPA logic lives here - just HTTP plumbing.
"""
from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

import io

from .schemas import (
    ExecuteRequest, ExecuteResponse, HealthResponse,
    OperationsListResponse, OperationInfo, ScreenshotAnalyzeRequest,
)

router = APIRouter()

# These are injected by main.py at startup
_engine = None          # OperationEngine instance (controller + finder + executor)
_config = None
_logger = None


def init_routes(engine, config, logger):
    """Called from main.py to inject dependencies."""
    global _engine, _config, _logger
    _engine = engine
    _config = config
    _logger = logger


@router.get("/health", response_model=HealthResponse)
async def health():
    """Check service and WeChat window status."""
    # TODO: check if WeChat window is accessible via controller
    return HealthResponse(
        status="ok",
        wechat_running=False,  # TODO: real check
        operations_count=len(__import__("src.operations.registry", fromlist=["OperationRegistry"]).OperationRegistry.list_all()),
    )


@router.get("/api/operations", response_model=OperationsListResponse)
async def list_operations():
    """List all registered operations."""
    from ..operations.registry import OperationRegistry
    ops = OperationRegistry.list_all()
    return OperationsListResponse(
        operations=[OperationInfo(**op) for op in ops]
    )


@router.post("/api/execute", response_model=ExecuteResponse)
async def execute_operation(req: ExecuteRequest):
    """Execute a WeChat operation.

    1. Look up operation class by name from registry
    2. Create operation instance
    3. Run through the lifecycle (pre_hook -> execute -> post_hook)
    4. Return result
    """
    from ..operations.registry import OperationRegistry

    op_class = OperationRegistry.get(req.operation)
    if op_class is None:
        raise HTTPException(status_code=404, detail=f"Operation '{req.operation}' not found")

    # TODO: create OperationContext with real controller/finder/config/logger
    # TODO: run operation via _engine.execute(op_class, ctx, req.params)
    # TODO: catch exceptions, return ExecuteResponse with FAILED status

    return ExecuteResponse(
        status="failed",
        message="Not implemented yet - engine wiring pending",
    )


@router.get("/api/screenshot")
async def screenshot():
    """Capture and return the current WeChat window as PNG."""
    # TODO: _engine.controller.screenshot() -> encode as PNG -> StreamingResponse
    raise HTTPException(status_code=501, detail="Not implemented yet")


@router.post("/api/screenshot/analyze")
async def analyze_screenshot(req: ScreenshotAnalyzeRequest):
    """Capture screenshot and analyze with AI vision."""
    # TODO:
    # 1. controller.screenshot()
    # 2. Encode as base64
    # 3. Send to LLM with req.prompt
    # 4. Return analysis text
    raise HTTPException(status_code=501, detail="Not implemented yet")
