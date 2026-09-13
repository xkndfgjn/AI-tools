"""WeChat local file operations - find / read / open files received via WeChat.

WeChat 4.x stores received (and sent) files on local disk, keeping the ORIGINAL
filename (unlike 3.x which hashed everything):

    <files_root>/<wxid>/msg/file/<YYYY-MM>/<original name>

This module exposes that store as operations, purely via the filesystem - no
database access, no process hooking, nothing private-protocol related:

- ``find_wechat_file``  - search files by name substring (newest first)
- ``read_wechat_file``  - read text-file content (line-limited preview)
- ``open_wechat_file``  - open with the OS default app

The files root is auto-discovered (config override available) because WeChat
lets users relocate it (e.g. ``D:\\xwechat_files``).
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Iterable, Optional

from .base import BaseOperation, OperationContext, OperationResult, OperationStatus
from .registry import register_operation

# ---------------------------------------------------------------------------
# Pure helpers (unit-tested)
# ---------------------------------------------------------------------------

# Candidate roots for the WeChat file store, probed in order.
# 4.x defaults to <USERPROFILE>\Documents\xwechat_files; users often relocate
# it to D:\xwechat_files etc. Config wechat.files_root overrides all probes.
def _default_files_roots() -> list[str]:
    roots = [
        r"D:\xwechat_files",
        r"C:\xwechat_files",
    ]
    docs = Path(os.environ.get("USERPROFILE", "")) / "Documents"
    roots.append(str(docs / "xwechat_files"))
    roots.append(str(docs / "WeChat Files"))  # 3.x layout, keep for compat
    return roots


_DEFAULT_FILES_ROOTS = _default_files_roots()


def resolve_files_root(config: dict,
                       probe_roots: Optional[list[str]] = None) -> Optional[str]:
    """Return the WeChat files root dir.

    - Explicit ``wechat.files_root`` in config is STRICT: returned only when it
      exists; a configured-but-missing dir returns None (no silent fallback,
      so config mistakes surface instead of being masked).
    - Otherwise probe common locations (override via ``probe_roots`` for tests).
    """
    cfg_root = (config.get("wechat", {}) or {}).get("files_root")
    if cfg_root:
        return cfg_root if os.path.isdir(cfg_root) else None
    roots = list(probe_roots) if probe_roots is not None else _DEFAULT_FILES_ROOTS
    for root in roots:
        if os.path.isdir(root):
            return root
    # Fall back to scanning Documents for xwechat_files.
    docs = Path(os.environ.get("USERPROFILE", "")) / "Documents"
    cand = docs / "xwechat_files"
    if cand.is_dir():
        return str(cand)
    return None


def _msg_file_dirs(root: str) -> list[Path]:
    """All `<root>/<wxid>/msg/file` directories (skip Backup/all_users)."""
    root_path = Path(root)
    if not root_path.is_dir():
        return []
    dirs = []
    for wxid in root_path.iterdir():
        if not wxid.is_dir():
            continue
        mf = wxid / "msg" / "file"
        if mf.is_dir():
            dirs.append(mf)
    return dirs


def _file_entries(dirs: Iterable[Path], keyword: str, max_results: int,
                  newest_first: bool = True) -> list[dict]:
    """Search filename substrings across the given msg/file dirs.

    Returns dicts: {path, name, size, modified_at, dir} sorted by mtime.
    """
    kw = (keyword or "").strip().lower()
    hits = []
    for d in dirs:
        try:
            it = d.rglob("*")
            for p in it:
                if not p.is_file():
                    continue
                name = p.name
                if kw and kw not in name.lower():
                    continue
                try:
                    st = p.stat()
                except OSError:
                    continue
                hits.append({
                    "path": str(p),
                    "name": name,
                    "size": st.st_size,
                    "modified_at": time.strftime("%Y-%m-%d %H:%M:%S",
                                                 time.localtime(st.st_mtime)),
                    "dir": str(p.parent),
                })
        except OSError:
            continue
    hits.sort(key=lambda e: os.path.getmtime(e["path"]), reverse=newest_first)
    return hits[:max_results]


_TEXT_EXTENSIONS = {
    ".txt", ".md", ".csv", ".tsv", ".json", ".log", ".yaml", ".yml", ".ini",
    ".cfg", ".conf", ".xml", ".html", ".htm", ".css", ".js", ".ts", ".py",
    ".c", ".h", ".cpp", ".hpp", ".java", ".go", ".rs", ".sh", ".bat", ".sql",
    ".svg", ".toml", ".rst", ".rtf",
}


def is_text_file(path: str) -> bool:
    """True if the extension is in the known text set."""
    return Path(path).suffix.lower() in _TEXT_EXTENSIONS


def read_text_preview(path: str, limit_lines: int = 200,
                      max_line_len: int = 2000) -> dict:
    """Read the first `limit_lines` of a text file with encoding tolerance.

    Returns {line_count, content (str), truncated: bool, encoding}.
    Never raises on decoding errors (gbk fallback, errors="replace").
    """
    encodings = ["utf-8", "gbk", "latin-1"]
    used = "utf-8"
    for enc in encodings:
        try:
            with open(path, "r", encoding=enc) as f:
                lines = f.readlines()
            used = enc
            break
        except (UnicodeDecodeError, UnicodeError):
            continue
    else:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        used = "utf-8(replace)"

    total = len(lines)
    shown = lines[:limit_lines]
    truncated = total > limit_lines
    # Trim any single overly-long line to keep the payload sane.
    content = "".join(
        line if len(line) <= max_line_len else line[:max_line_len] + "...\n"
        for line in shown
    )
    return {
        "line_count": total,
        "content": content,
        "truncated": truncated,
        "encoding": used,
    }


def resolve_file_path(config: dict, params: dict) -> tuple[Optional[str], str]:
    """Resolve `path` or `keyword` param to an absolute file path.

    Returns (path_or_None, error_message).
    """
    path = params.get("path")
    if path:
        if not os.path.isfile(path):
            return None, f"File not found: {path}"
        return path, ""

    keyword = params.get("keyword")
    if not keyword:
        return None, "Missing parameter: path (or keyword to search)"
    root = resolve_files_root(config)
    if not root:
        return None, "WeChat files root not found; set config wechat.files_root"
    entries = _file_entries(_msg_file_dirs(root), keyword, max_results=1)
    if not entries:
        return None, f"No WeChat file matches keyword: {keyword}"
    return entries[0]["path"], ""


# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------

@register_operation("find_wechat_file")
class FindWeChatFileOperation(BaseOperation):
    description = "Search files received via WeChat on local disk by name"

    async def execute(self, ctx: OperationContext, params: dict) -> OperationResult:
        keyword = params.get("keyword")
        if not keyword:
            return OperationResult(
                status=OperationStatus.FAILED,
                message="Missing parameter: keyword",
            )
        max_results = max(1, min(int(params.get("max_results", 10)), 50))

        root = resolve_files_root(ctx.config)
        if not root:
            return OperationResult(
                status=OperationStatus.FAILED,
                message="WeChat files root not found; set config wechat.files_root",
            )

        entries = _file_entries(_msg_file_dirs(root), keyword, max_results)
        return OperationResult(
            status=OperationStatus.SUCCESS,
            data={"files": entries, "count": len(entries), "root": root},
            message=f"Found {len(entries)} file(s) matching '{keyword}'",
        )


@register_operation("read_wechat_file")
class ReadWeChatFileOperation(BaseOperation):
    description = "Read text content of a file received via WeChat"

    async def execute(self, ctx: OperationContext, params: dict) -> OperationResult:
        path, err = resolve_file_path(ctx.config, params)
        if not path:
            return OperationResult(status=OperationStatus.FAILED, message=err)
        if not is_text_file(path):
            return OperationResult(
                status=OperationStatus.FAILED,
                message=(
                    f"Not a text file ({Path(path).suffix}); read unsupported. "
                    f"Use open_wechat_file instead."
                ),
            )
        limit = max(1, min(int(params.get("limit", 200)), 2000))
        try:
            preview = read_text_preview(path, limit_lines=limit)
        except OSError as e:
            return OperationResult(
                status=OperationStatus.FAILED,
                message=f"Failed to read {path}: {e}",
            )

        return OperationResult(
            status=OperationStatus.SUCCESS,
            data={
                "path": path,
                "size": os.path.getsize(path),
                **preview,
            },
            message=f"Read {preview['line_count']} lines from {Path(path).name}",
        )


@register_operation("open_wechat_file")
class OpenWeChatFileOperation(BaseOperation):
    description = "Open a file received via WeChat with the system default app"

    async def execute(self, ctx: OperationContext, params: dict) -> OperationResult:
        path, err = resolve_file_path(ctx.config, params)
        if not path:
            return OperationResult(status=OperationStatus.FAILED, message=err)
        try:
            os.startfile(path)  # type: ignore[attr-defined]  # Windows only
        except OSError as e:
            return OperationResult(
                status=OperationStatus.FAILED,
                message=f"Failed to open {path}: {e}",
            )
        return OperationResult(
            status=OperationStatus.SUCCESS,
            data={"path": path, "name": Path(path).name},
            message=f"Opened '{Path(path).name}' with default app",
        )
