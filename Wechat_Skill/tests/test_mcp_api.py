"""HTTP-level smoke tests for the MCP facade routes.

These hit /api/mcp/tools and the validation paths of /api/mcp/call. They do
NOT execute real RPA operations (unknown-tool / missing-field errors are
raised before the transport touches the engine), so they run without WeChat.
"""
from fastapi.testclient import TestClient


def _client():
    from src.main import app
    return TestClient(app)


def test_mcp_tools_lists_six():
    resp = _client().get("/api/mcp/tools")
    assert resp.status_code == 200
    tools = set(resp.json()["tools"])
    assert tools == {
        "open_chat",
        "send_message",
        "send_file",
        "read_messages",
        "list_sessions",
        "broadcast_message",
    }


def test_mcp_call_unknown_tool_returns_404():
    resp = _client().post("/api/mcp/call", json={"tool": "nope", "params": {}})
    assert resp.status_code == 404
    assert "Unknown operation/tool" in resp.json()["detail"]


def test_mcp_call_missing_required_field_returns_400():
    resp = _client().post("/api/mcp/call", json={"tool": "send_message", "params": {}})
    assert resp.status_code == 400
    assert "missing required fields" in resp.json()["detail"]
