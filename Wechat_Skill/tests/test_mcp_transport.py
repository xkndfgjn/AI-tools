"""Tests for the OperationEngineTransport bridge + build_default_facade.

These use a FakeEngine instead of the real OperationEngine, so they run
without WeChat / RPA hardware. They verify the transport resolves the
operation class by name, awaits engine.execute, and serializes the
OperationResult; and that build_default_facade registers all 6 ops as tools
with the right required_fields.
"""
import asyncio

import pytest

from src.mcp import OperationEngineTransport, build_default_facade
from src.operations.base import OperationResult, OperationStatus


class FakeEngine:
    """Stand-in for OperationEngine: records calls, returns a fake result."""

    def __init__(self):
        self.calls = []

    async def execute(self, op_class, params):
        self.calls.append((op_class.name, params))
        return OperationResult(
            status=OperationStatus.SUCCESS,
            data={"echo": params},
            message=f"ran {op_class.name}",
        )


@pytest.fixture(autouse=True)
def _ensure_ops_registered():
    # Importing the operations package triggers @register_operation for all 6
    # ops, so OperationRegistry.get(name) resolves in the transport.
    import src.operations  # noqa: F401


def test_transport_resolves_operation_and_serializes_result():
    engine = FakeEngine()
    transport = OperationEngineTransport(engine)

    out = asyncio.run(
        transport.call_tool("send_message", {"to": "老妈", "text": "hi"})
    )

    assert out["status"] == "success"
    assert out["data"] == {"echo": {"to": "老妈", "text": "hi"}}
    assert out["message"] == "ran send_message"
    assert engine.calls == [("send_message", {"to": "老妈", "text": "hi"})]


def test_transport_unknown_tool_raises():
    engine = FakeEngine()
    transport = OperationEngineTransport(engine)

    with pytest.raises(ValueError, match="Unknown operation/tool"):
        asyncio.run(transport.call_tool("nope", {}))


def test_build_default_facade_registers_six_tools():
    facade = build_default_facade(FakeEngine())
    assert set(facade.list_tools()) == {
        "open_chat",
        "send_message",
        "send_file",
        "read_messages",
        "list_sessions",
        "broadcast_message",
    }


def test_build_default_facade_required_fields():
    facade = build_default_facade(FakeEngine())
    assert facade.registry.get("send_message").required_fields == ["to", "text"]
    assert facade.registry.get("send_file").required_fields == ["to", "file_path"]
    assert facade.registry.get("broadcast_message").required_fields == ["targets", "text"]
    # Operations that accept aliases validate themselves (no strict fields).
    assert facade.registry.get("open_chat").required_fields == []
    assert facade.registry.get("read_messages").required_fields == []
    assert facade.registry.get("list_sessions").required_fields == []
