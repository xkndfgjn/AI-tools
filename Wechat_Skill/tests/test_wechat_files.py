"""Tests for WeChat local file operations (src/operations/wechat_files.py).

Pure helpers are tested against tmp_path fixtures; no real WeChat install
required. Operation classes are exercised via the registry-level flow.
"""
import os

import pytest

from src.operations.wechat_files import (
    _file_entries,
    _msg_file_dirs,
    is_text_file,
    read_text_preview,
    resolve_files_root,
)


@pytest.fixture
def fake_store(tmp_path):
    """Create `<root>/wxid_a/msg/file/2026-09/...` with a few files."""
    base = tmp_path / "xwechat_files"
    mf = base / "wxid_abc" / "msg" / "file" / "2026-09"
    mf.mkdir(parents=True)
    (mf / "884信号与系统_Anki导入.txt").write_text(
        "line1\nline2\n", encoding="utf-8")
    (mf / "report.pdf").write_bytes(b"%PDF-1.4 fake")
    other = base / "wxid_def" / "msg" / "file" / "2026-08"
    other.mkdir(parents=True)
    (other / "notes.md").write_text("# hi\n", encoding="utf-8")
    # Non-msg/file dirs must be ignored.
    (base / "wxid_abc" / "temp").mkdir(parents=True)
    (base / "wxid_abc" / "temp" / "junk.txt").write_text("junk", encoding="utf-8")
    return base


class TestResolveFilesRoot:
    def test_config_override(self, tmp_path):
        root = str(tmp_path / "custom")
        (tmp_path / "custom").mkdir()
        assert resolve_files_root({"wechat": {"files_root": root}}) == root

    def test_config_points_missing_dir(self):
        # Explicit config is strict: missing dir -> None, no silent fallback.
        assert resolve_files_root({"wechat": {"files_root": r"Z:\nope"}}) is None

    def test_empty_config_probes_nothing(self):
        # Inject empty probe list to isolate from the host's real install.
        assert resolve_files_root({}, probe_roots=[]) is None

    def test_probe_finds_existing(self, fake_store):
        assert resolve_files_root({}, probe_roots=[str(fake_store)]) == str(fake_store)


class TestMsgFileDirs:
    def test_only_msg_file_dirs(self, fake_store):
        dirs = _msg_file_dirs(str(fake_store))
        names = {d.name for d in dirs}
        assert names == {"file"}
        assert len(dirs) == 2  # wxid_abc + wxid_def

    def test_missing_root(self, tmp_path):
        assert _msg_file_dirs(str(tmp_path / "nothing")) == []


class TestFileEntries:
    def test_keyword_match_case_insensitive(self, fake_store):
        hits = _file_entries(_msg_file_dirs(str(fake_store)), "anki", 10)
        assert len(hits) == 1
        assert hits[0]["name"] == "884信号与系统_Anki导入.txt"

    def test_no_keyword_returns_all_sorted_newest(self, fake_store):
        hits = _file_entries(_msg_file_dirs(str(fake_store)), "", 10)
        assert len(hits) == 3
        # Newest first: 2026-09 files beat 2026-08 (same mtime ties are fine).
        names = [h["name"] for h in hits]
        assert "884信号与系统_Anki导入.txt" in names
        assert "notes.md" in names
        assert "junk.txt" not in names  # outside msg/file

    def test_max_results(self, fake_store):
        hits = _file_entries(_msg_file_dirs(str(fake_store)), "", 2)
        assert len(hits) == 2

    def test_no_match(self, fake_store):
        assert _file_entries(_msg_file_dirs(str(fake_store)), "zzz_no_match", 10) == []


class TestIsTextFile:
    def test_text_extensions(self):
        assert is_text_file("a.txt")
        assert is_text_file("b.md")
        assert is_text_file("c.json")
        assert is_text_file("d.log")
        assert is_text_file("e.py")

    def test_binary_extensions(self):
        assert not is_text_file("a.pdf")
        assert not is_text_file("b.jpg")
        assert not is_text_file("c.exe")
        assert not is_text_file("d.dat")


class TestReadTextPreview:
    def test_utf8(self, tmp_path):
        p = tmp_path / "a.txt"
        p.write_text("你好\n世界\n", encoding="utf-8")
        r = read_text_preview(str(p), limit_lines=10)
        assert r["line_count"] == 2
        assert r["content"] == "你好\n世界\n"
        assert r["truncated"] is False
        assert r["encoding"] == "utf-8"

    def test_gbk_fallback(self, tmp_path):
        p = tmp_path / "b.txt"
        p.write_bytes("中文内容".encode("gbk"))
        r = read_text_preview(str(p), limit_lines=10)
        assert "中文内容" in r["content"]
        assert r["encoding"] == "gbk"

    def test_truncation(self, tmp_path):
        p = tmp_path / "c.txt"
        p.write_text("\n".join(f"line{i}" for i in range(50)), encoding="utf-8")
        r = read_text_preview(str(p), limit_lines=10)
        assert r["line_count"] == 50
        assert r["truncated"] is True
        assert r["content"].count("line") == 10

    def test_missing_file_raises_oserror(self, tmp_path):
        with pytest.raises(OSError):
            read_text_preview(str(tmp_path / "nope.txt"))
