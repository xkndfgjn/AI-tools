import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.operations.contacts import parse_session_entries


def _block(text, cx, cy, w, h, conf=0.99):
    return {
        "text": text,
        "confidence": conf,
        "center_x": cx,
        "center_y": cy,
        "width": w,
        "height": h,
        "box": [[cx - w // 2, cy - h // 2], [cx + w // 2, cy - h // 2], [cx + w // 2, cy + h // 2], [cx - w // 2, cy + h // 2]],
    }


def test_parse_session_entries_ignores_sidebar_labels_and_time():
    blocks = [
        _block("微信", 50, 40, 40, 18),
        _block("通讯录", 50, 70, 60, 18),
        _block("老妈", 170, 110, 70, 22),
        _block("今天吃饭了吗", 170, 140, 200, 18),
        _block("16:11", 350, 112, 40, 18),
        _block("文件传输助手", 170, 220, 150, 22),
        _block("你好", 170, 250, 80, 18),
        _block("09:48", 350, 222, 40, 18),
    ]

    sessions = parse_session_entries(blocks)

    assert [s["name"] for s in sessions] == ["老妈", "文件传输助手"]
    assert sessions[0]["preview"] == "今天吃饭了吗"
    assert sessions[0]["time"] == "16:11"
    assert sessions[0]["source"] == "ocr"


def test_parse_session_entries_groups_same_row_into_one_session():
    blocks = [
        _block("张三", 150, 200, 80, 22),
        _block("你今天去哪儿了", 150, 225, 160, 18),
        _block("10:12", 360, 200, 38, 18),
        _block("李四", 150, 320, 80, 22),
        _block("明天见", 150, 345, 120, 18),
        _block("11:30", 360, 320, 38, 18),
    ]

    sessions = parse_session_entries(blocks)

    assert [s["name"] for s in sessions] == ["张三", "李四"]
    assert sessions[0]["preview"] == "你今天去哪儿了"
    assert sessions[1]["time"] == "11:30"
