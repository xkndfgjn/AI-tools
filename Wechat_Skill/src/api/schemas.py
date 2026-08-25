"""Pydantic schemas for API request/response validation."""
from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, Field


class ExecuteRequest(BaseModel):
    """Request body for POST /api/execute."""
    operation: str = Field(..., description="Operation name, e.g. 'send_message'")
    params: dict = Field(default_factory=dict, description="Operation parameters")


class ExecuteResponse(BaseModel):
    """Response for POST /api/execute."""
    status: str = Field(..., description="success | failed | needs_confirmation")
    data: Optional[Any] = None
    message: str = ""
    screenshots: list[str] = Field(default_factory=list)
    duration_ms: int = 0


class HealthResponse(BaseModel):
    """Response for GET /health."""
    status: str = "ok"
    wechat_running: bool = False
    wechat_window: Optional[str] = None
    window_rect: Optional[list[int]] = None
    operations_count: int = 0


class OperationInfo(BaseModel):
    """Info about a single registered operation."""
    name: str
    description: str = ""
    requires_confirmation: bool = False


class OperationsListResponse(BaseModel):
    """Response for GET /api/operations."""
    operations: list[OperationInfo]


class ScreenshotAnalyzeRequest(BaseModel):
    """Request body for POST /api/screenshot/analyze."""
    prompt: str = Field(..., description="Question about the current WeChat screen")
