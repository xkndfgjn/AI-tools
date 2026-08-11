from pathlib import Path

import fitz
from mcp.types import TextContent


def _read_pdf(path: str) -> fitz.Document:
    return fitz.open(path)


async def pdf_extract_text(file_path: str, page_start: int = 0, page_end: int = -1) -> list[TextContent]:
    """从 PDF 提取文本，支持指定页码范围。"""
    path = Path(file_path)
    if not path.exists():
        return [TextContent(type="text", text=f"错误：文件不存在 {file_path}")]
    if path.suffix.lower() != ".pdf":
        return [TextContent(type="text", text="错误：不是 pdf 文件")]

    doc = _read_pdf(str(path))
    try:
        total_pages = doc.page_count
        if page_end == -1 or page_end >= total_pages:
            page_end = total_pages - 1
        if page_end < 0:
            page_end = 0
        if page_start < 0:
            page_start = 0
        if page_start > page_end:
            return [TextContent(type="text", text="错误：页码范围无效")]

        chunks = []
        for idx in range(page_start, page_end + 1):
            page = doc.load_page(idx)
            text = page.get_text()
            chunks.append(f"===== Page {idx + 1} =====\n{text}\n")
        return [TextContent(type="text", text="".join(chunks))]
    finally:
        doc.close()
