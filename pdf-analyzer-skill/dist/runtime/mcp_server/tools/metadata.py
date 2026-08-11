from pathlib import Path

import fitz
from mcp.types import TextContent


async def pdf_get_metadata(file_path: str) -> list[TextContent]:
    """获取 PDF 元数据。"""
    path = Path(file_path)
    if not path.exists():
        return [TextContent(type="text", text=f"错误：文件不存在 {file_path}")]
    if path.suffix.lower() != ".pdf":
        return [TextContent(type="text", text="错误：不是 pdf 文件")]

    doc = fitz.open(str(path))
    try:
        meta = dict(doc.metadata or {})
        meta["pages"] = doc.page_count
        lines = [f"{k}: {v}" for k, v in meta.items()]
        return [TextContent(type="text", text="\n".join(lines))]
    finally:
        doc.close()
