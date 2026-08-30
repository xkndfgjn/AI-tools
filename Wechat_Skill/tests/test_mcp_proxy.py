import asyncio

import pytest

from src.mcp import SkillMcpFacade, ToolResponse


class FakeTransport:
    """Async no-op transport that records calls (mirrors BaseMcpTransport)."""

    def __init__(self):
        self.calls = []

    async def call_tool(self, tool_name, params):
        self.calls.append((tool_name, params))
        return {"ok": True, "tool": tool_name, "params": params}


def test_skill_facade_calls_through_adapter():
    transport = FakeTransport()
    facade = SkillMcpFacade(transport=transport)

    response = asyncio.run(facade.call("search_files", {"query": "readme"}))

    assert isinstance(response, ToolResponse)
    assert response.ok is True
    assert response.tool == "search_files"
    assert response.result == {"ok": True, "tool": "search_files", "params": {"query": "readme"}}
    assert transport.calls == [("search_files", {"query": "readme"})]


def test_skill_facade_blocks_direct_mcp_access():
    transport = FakeTransport()
    facade = SkillMcpFacade(transport=transport)

    with pytest.raises(RuntimeError, match="Skill facade"):
        facade.call_tool("search_files", {"query": "readme"})


def test_registry_validates_required_fields():
    transport = FakeTransport()
    facade = SkillMcpFacade(transport=transport)
    facade.register_tool("read_file", "read a file", required_fields=["path"])

    with pytest.raises(ValueError, match="missing required fields"):
        asyncio.run(facade.call("read_file", {}))


def test_facade_lists_registered_tools():
    transport = FakeTransport()
    facade = SkillMcpFacade(transport=transport)
    facade.register_tool("search_files", "search", required_fields=["query"])
    facade.register_tool("read_file", "read", required_fields=["path"])

    assert facade.list_tools() == ["search_files", "read_file"]
