"""MCP facade - agent-facing tool entrypoint bridged to the RPA engine.

Public API::

    facade = build_default_facade(engine)            # wired to real OperationEngine
    resp = await facade.call("send_message", {"to": "...", "text": "..."})
    # resp: ToolResponse(ok, tool, result, message)

Design:
- `SkillMcpFacade.call()` is the ONLY supported entrypoint for external tool
  invocation. It is **async** because it bridges to the async OperationEngine
  (whose serial asyncio.Lock is bound to the running event loop - blocking it
  synchronously from inside that loop would deadlock).
- `SkillMcpFacade.call_tool()` is intentionally disabled (raises RuntimeError)
  to enforce the facade boundary; agents must use `call()`.
- `OperationEngineTransport.call_tool(name, params)` resolves the operation
  class via `OperationRegistry.get(name)` and awaits `engine.execute(op_class,
  params)`, serializing the returned OperationResult to a plain dict.
- `build_default_facade(engine)` registers the 6 RPA operations as tools with
  their required fields.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class ToolResponse:
    """Normalized response returned by the Skill facade."""
    ok: bool
    tool: str
    result: Any
    message: str = ""


@dataclass
class ToolSpec:
    """Metadata for a tool exposed through the facade."""
    name: str
    description: str = ""
    required_fields: List[str] = field(default_factory=list)
    handler: Optional[Callable[[Dict[str, Any]], Any]] = None


class BaseMcpTransport:
    """Minimal async transport abstraction behind the facade.

    The agent never talks to this layer directly; the Skill facade is the
    intended public API.
    """

    async def call_tool(self, tool_name: str, params: Dict[str, Any]) -> Any:
        raise NotImplementedError


class ToolRegistry:
    """Registry of MCP tools exposed by the skill facade."""

    def __init__(self):
        self._tools: Dict[str, ToolSpec] = {}

    def register(self, name: str, description: str = "", required_fields: Optional[List[str]] = None,
                 handler: Optional[Callable[[Dict[str, Any]], Any]] = None):
        self._tools[name] = ToolSpec(
            name=name,
            description=description,
            required_fields=list(required_fields or []),
            handler=handler,
        )
        return self._tools[name]

    def get(self, name: str) -> Optional[ToolSpec]:
        return self._tools.get(name)

    def list(self) -> List[ToolSpec]:
        return list(self._tools.values())

    def validate(self, name: str, params: Dict[str, Any]) -> None:
        spec = self.get(name)
        if spec is None:
            # Unknown tool: pass through; the transport raises a clear error.
            # This lets validate() focus on required-field checks for known
            # tools while still surfacing unknown tools at dispatch time.
            return
        missing = [field for field in spec.required_fields if field not in params]
        if missing:
            raise ValueError(f"Tool '{name}' missing required fields: {missing}")


@dataclass
class McpConnectionState:
    """Connection lifecycle state for the MCP adapter."""
    connected: bool = False
    session_id: Optional[str] = None
    last_error: Optional[str] = None
    tool_count: int = 0


class McpSessionManager:
    """Small connection/session manager behind the skill facade."""

    def __init__(self, transport: Optional[BaseMcpTransport] = None, registry: Optional[ToolRegistry] = None):
        self.transport = transport or _DefaultMcpTransport()
        self.registry = registry or ToolRegistry()
        self.state = McpConnectionState(tool_count=0)

    def connect(self, session_id: Optional[str] = None) -> McpConnectionState:
        self.state.connected = True
        self.state.session_id = session_id or "session-default"
        self.state.last_error = None
        self.state.tool_count = len(self.registry.list())
        return self.state

    def disconnect(self):
        self.state.connected = False
        self.state.last_error = None

    async def call_tool(self, tool_name: str, params: Optional[Dict[str, Any]] = None) -> Any:
        if not self.state.connected:
            raise RuntimeError("MCP session is not connected")
        payload = params or {}
        self.registry.validate(tool_name, payload)
        return await self.transport.call_tool(tool_name, payload)


class SkillMcpFacade:
    """Agent-facing wrapper for external MCP calls.

    Design goal:
    - Agent calls this facade
    - Facade decides the MCP tool call
    - Connection/session behavior is centralized here
    - Raw MCP access is hidden behind a stable interface
    """

    def __init__(self, transport: Optional[BaseMcpTransport] = None, registry: Optional[ToolRegistry] = None,
                 session_manager: Optional[McpSessionManager] = None):
        self.registry = registry or ToolRegistry()
        self.session_manager = session_manager or McpSessionManager(transport=transport, registry=self.registry)
        self.session_manager.connect(session_id="skill-facade")

    def register_tool(self, name: str, description: str = "", required_fields: Optional[List[str]] = None,
                     handler: Optional[Callable[[Dict[str, Any]], Any]] = None):
        return self.registry.register(name=name, description=description, required_fields=required_fields, handler=handler)

    async def call(self, tool_name: str, params: Optional[Dict[str, Any]] = None) -> ToolResponse:
        """Public API for the agent/skill layer.

        This is the only supported entrypoint for external tool invocation.
        It is async because the underlying OperationEngine is async.
        """
        payload = params or {}
        result = await self.session_manager.call_tool(tool_name, payload)
        return ToolResponse(
            ok=True,
            tool=tool_name,
            result=result,
            message=f"Executed MCP tool '{tool_name}' via Skill facade",
        )

    def call_tool(self, tool_name: str, params: Optional[Dict[str, Any]] = None):
        """Prevent direct low-level access.

        This method exists to enforce the architectural boundary: agents and
        skill code should not bypass the facade.
        """
        raise RuntimeError(
            "Skill facade blocks direct MCP tool access. Use call() instead."
        )

    def list_tools(self) -> List[str]:
        return [spec.name for spec in self.registry.list()]


class _DefaultMcpTransport(BaseMcpTransport):
    """Default no-op transport used for tests or local scaffolding."""

    async def call_tool(self, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        return {"ok": True, "tool": tool_name, "params": params}


def _operation_result_to_dict(result: Any) -> Dict[str, Any]:
    """Serialize an OperationResult to a JSON-friendly dict."""
    status = getattr(result, "status", None)
    status_value = getattr(status, "value", status)
    return {
        "status": status_value,
        "data": getattr(result, "data", None),
        "message": getattr(result, "message", ""),
        "screenshots": list(getattr(result, "screenshots", []) or []),
        "duration_ms": getattr(result, "duration_ms", 0),
    }


class OperationEngineTransport(BaseMcpTransport):
    """Bridge the Skill facade to the real RPA OperationEngine.

    `call_tool(tool_name, params)` resolves the operation class via
    `OperationRegistry.get(tool_name)` and awaits
    `engine.execute(op_class, params)`. The returned OperationResult is
    serialized to a plain dict so the facade / API layer can return it as JSON.
    """

    def __init__(self, engine: Any):
        self._engine = engine

    async def call_tool(self, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        # Lazy import avoids any module-load-time import cycle between
        # mcp <-> operations. Operations are registered by the time any call
        # happens (main.py imports src.operations at startup).
        from .operations.registry import OperationRegistry

        op_class = OperationRegistry.get(tool_name)
        if op_class is None:
            raise ValueError(f"Unknown operation/tool: '{tool_name}'")
        result = await self._engine.execute(op_class, params or {})
        return _operation_result_to_dict(result)


# (tool_name, description, required_fields). required_fields is empty for
# operations that accept aliases (open_chat: name/to/chat; read_messages:
# chat/to) so the operation's own validation handles them.
_DEFAULT_TOOL_SPECS: List[tuple] = [
    ("open_chat", "Search for a contact/group and open the chat window", []),
    ("send_message", "Send a text message to a contact or group", ["to", "text"]),
    ("send_file", "Send a file or image to a contact or group", ["to", "file_path"]),
    ("read_messages", "Read recent messages from a chat", []),
    ("list_sessions", "List recent chat sessions from the sidebar", []),
    ("broadcast_message", "Send the same text message to multiple contacts/groups", ["targets", "text"]),
]


def _register_default_tools(registry: ToolRegistry) -> None:
    for name, description, required in _DEFAULT_TOOL_SPECS:
        registry.register(name, description=description, required_fields=required)


def build_default_facade(engine: Any) -> SkillMcpFacade:
    """Build a SkillMcpFacade wired to the real OperationEngine and register
    the 6 RPA operations as MCP tools.

    Call this once at app startup. The facade only stores the engine
    reference; it dispatches to engine.execute() at call time, by which
    point startup has initialized the controller.
    """
    registry = ToolRegistry()
    _register_default_tools(registry)
    transport = OperationEngineTransport(engine)
    return SkillMcpFacade(transport=transport, registry=registry)
