"""Basic API smoke tests.

Run with: python -m pytest tests/test_api.py -v
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from src.main import app
    return TestClient(app)


def test_health(client):
    """GET /health should return 200 with status ok."""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"


def test_list_operations(client):
    """GET /api/operations should return registered operations."""
    resp = client.get("/api/operations")
    assert resp.status_code == 200
    data = resp.json()
    assert "operations" in data
    names = [op["name"] for op in data["operations"]]
    assert "send_message" in names
    assert "read_messages" in names


def test_execute_unknown_operation(client):
    """POST /api/execute with unknown operation should return 404."""
    resp = client.post("/api/execute", json={
        "operation": "nonexistent",
        "params": {}
    })
    assert resp.status_code == 404
