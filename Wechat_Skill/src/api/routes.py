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
    McpCallRequest,
)

router = APIRouter()

# These are injected by main.py at startup
_engine = None          # OperationEngine instance (controller + finder + executor)
_config = None
_logger = None
_facade = None          # SkillMcpFacade instance (MCP tool entrypoint)


def init_routes(engine, config, logger, facade=None):
    """Called from main.py to inject dependencies."""
    global _engine, _config, _logger, _facade
    _engine = engine
    _config = config
    _logger = logger
    _facade = facade


@router.get("/health", response_model=HealthResponse)
async def health():
    """Check service and WeChat window status."""
    wechat_running = False
    window_rect = None
    wechat_window = None

    if _engine and _engine.controller:
        try:
            hwnd = await asyncio.to_thread(_engine.controller.find_wechat_window)
            wechat_running = bool(hwnd)
            if wechat_running:
                wechat_window = f"HWND:{hwnd}"
                rect = _engine.controller.get_window_rect()
                if rect:
                    window_rect = list(rect)
        except Exception as e:
            if _logger:
                _logger.debug(f"health check controller error: {e}")

    return HealthResponse(
        status="ok",
        wechat_running=wechat_running,
        wechat_window=wechat_window,
        window_rect=window_rect,
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
    """Execute a WeChat operation."""
    from ..operations.registry import OperationRegistry

    op_class = OperationRegistry.get(req.operation)
    if op_class is None:
        raise HTTPException(status_code=404, detail=f"Operation '{req.operation}' not found")

    if _engine is None or _engine.controller is None:
        return ExecuteResponse(
            status="failed",
            message="RPA engine not initialized",
        )

    try:
        result = await _engine.execute(op_class, req.params)
        return ExecuteResponse(
            status=result.status.value,
            data=result.data,
            message=result.message,
            screenshots=result.screenshots,
            duration_ms=result.duration_ms,
        )
    except Exception as e:
        if _logger:
            _logger.exception("execute_operation failed")
        return ExecuteResponse(
            status="failed",
            message=str(e),
        )


@router.get("/api/screenshot")
async def screenshot():
    """Capture and return the current WeChat window as PNG."""
    if _engine is None or _engine.controller is None:
        raise HTTPException(status_code=503, detail="RPA engine not initialized")

    try:
        img = await asyncio.to_thread(_engine.controller.screenshot)
        from ..rpa.screenshot import ScreenshotUtil
        path = _engine.controller.save_screenshot(image=img)
        with open(path, "rb") as f:
            data = f.read()
        return StreamingResponse(io.BytesIO(data), media_type="image/png")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Screenshot failed: {e}")


@router.post("/api/screenshot/analyze")
async def analyze_screenshot(req: ScreenshotAnalyzeRequest):
    """Capture screenshot and analyze with AI vision."""
    # TODO:
    # 1. controller.screenshot()
    # 2. Encode as base64
    # 3. Send to LLM with req.prompt
    # 4. Return analysis text
    raise HTTPException(status_code=501, detail="Not implemented yet")


@router.get("/api/debug/control_tree")
async def debug_control_tree(
    name: Optional[str] = None,
    control_type: Optional[str] = None,
    depth: int = 3,
):
    """Dump the WeChat control tree for calibration.

    Useful for verifying whether uiautomation can see WeChat controls.
    """
    if _engine is None or _engine.controller is None:
        raise HTTPException(status_code=503, detail="RPA engine not initialized")

    infos = await asyncio.to_thread(
        _engine.controller.find_controls_info,
        name=name or None,
        control_type=control_type or None,
        depth=depth,
    )
    return {
        "count": len(infos),
        "window_rect": _engine.controller.get_window_rect(),
        "controls": infos[:200],  # cap to avoid huge responses
    }


@router.get("/api/debug/ocr")
async def debug_ocr():
    """Full-window OCR dump - calibrate search/region params with this.

    On Qt WeChat the control tree is empty, so this is the primary way to
    see what the OCR engine recognizes and where. Tip: trigger Ctrl+F +
    type a name in WeChat, then call this endpoint to tune config['search'].
    """
    if _engine is None or _engine.controller is None:
        raise HTTPException(status_code=503, detail="RPA engine not initialized")
    try:
        img = await asyncio.to_thread(_engine.controller.screenshot)
        from ..rpa.ocr_engine import OcrEngine
        items = await asyncio.to_thread(OcrEngine.get(_config).extract, img)
        rect = _engine.controller.get_window_rect()
        return {
            "count": len(items),
            "window_rect": list(rect) if rect else None,
            "items": items[:300],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OCR failed: {e}")


@router.get("/api/mcp/tools")
async def mcp_tools():
    """List MCP tools registered on the Skill facade."""
    if _facade is None:
        raise HTTPException(status_code=503, detail="MCP facade not initialized")
    return {"tools": _facade.list_tools()}


@router.post("/api/mcp/call")
async def mcp_call(req: McpCallRequest):
    """Invoke an MCP tool through the Skill facade.

    Body: {"tool": "send_message", "params": {"to": "...", "text": "..."}}
    The facade validates required fields, then the OperationEngineTransport
    awaits OperationEngine.execute(op_class, params) on this event loop.
    """
    if _facade is None:
        raise HTTPException(status_code=503, detail="MCP facade not initialized")
    try:
        resp = await _facade.call(req.tool, req.params)
    except ValueError as e:
        msg = str(e)
        status_code = 404 if "Unknown operation/tool" in msg else 400
        raise HTTPException(status_code=status_code, detail=msg)
    return {
        "ok": resp.ok,
        "tool": resp.tool,
        "result": resp.result,
        "message": resp.message,
    }
