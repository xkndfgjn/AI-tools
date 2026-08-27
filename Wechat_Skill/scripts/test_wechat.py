"""Manual WeChat RPA test script.

Usage:
    python scripts/test_wechat.py 文件传输助手
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

BASE = "http://127.0.0.1:9420"
PROJECT = Path(__file__).parent.parent


def api(method: str, path: str, body: dict | None = None) -> dict:
    url = f"{BASE}{path}"
    print(f"\n>>> {method} {url}")
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"} if data else {},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            text = resp.read().decode("utf-8")
            print(text)
            return json.loads(text)
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8")
        print(f"HTTP {e.code}: {text}")
        return {"status": "error", "message": text}


def save_bytes(url: str, path: Path) -> None:
    with urllib.request.urlopen(url, timeout=30) as resp:
        path.write_bytes(resp.read())


def main() -> int:
    contact = sys.argv[1] if len(sys.argv) > 1 else "老妈"
    print(f"测试联系人/群: {contact}")

    # 1. health
    api("GET", "/health")

    # 2. control tree
    tree = api("GET", "/api/debug/control_tree?depth=3")
    tree_path = PROJECT / "data" / "control_tree.json"
    tree_path.write_text(json.dumps(tree, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"控件树已保存到 {tree_path}")

    # 3. screenshot
    screenshot_path = PROJECT / "data" / "screenshots" / "test_screenshot.png"
    save_bytes(f"{BASE}/api/screenshot", screenshot_path)
    print(f"截图已保存到 {screenshot_path}")

    # 4. send message
    msg = f"RPA 测试消息 {datetime.now().strftime('%H:%M:%S')}"
    api("POST", "/api/execute", {
        "operation": "send_message",
        "params": {"to": contact, "text": msg},
    })

    # 5. read messages
    api("POST", "/api/execute", {
        "operation": "read_messages",
        "params": {"chat": contact, "limit": 10},
    })

    return 0


if __name__ == "__main__":
    sys.exit(main())
