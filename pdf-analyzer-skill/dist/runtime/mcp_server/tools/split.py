from pathlib import Path

import fitz
from mcp.types import TextContent


async def pdf_split(file_path: str, output_file: str, page_start: int, page_end: int) -> list[TextContent]:
    """分割 PDF，生成一个新的 PDF。"""
    src_path = Path(file_path)
    out_path = Path(output_file)
    if not src_path.exists():
        return [TextContent(type="text", text=f"错误：源PDF不存在 {file_path}")]
    if src_path.suffix.lower() != ".pdf":
        return [TextContent(type="text", text="错误：不是 pdf 文件")]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    src_doc = fitz.open(str(src_path))
    try:
        total = src_doc.page_count
        if page_start < 0 or page_end >= total or page_start > page_end:
            return [TextContent(type="text", text=f"页码越界，文档总页数:{total}，页码0~{total - 1}")]

        new_doc = fitz.open()
        try:
            new_doc.insert_pdf(src_doc, from_page=page_start, to_page=page_end)
            new_doc.save(str(out_path))
            return [TextContent(type="text", text=f"分割完成，输出文件：{output_file}，页数：{page_end - page_start + 1}")]
        finally:
            new_doc.close()
    finally:
        src_doc.close()
