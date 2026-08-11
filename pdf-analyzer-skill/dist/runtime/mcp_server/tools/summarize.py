from pathlib import Path
from typing import cast

import fitz
from mcp.types import TextContent


async def pdf_summarize(file_path: str, length: int = 200) -> list[TextContent]:
    """对 PDF 文本做一个简短摘要。"""
    path = Path(file_path)
    if not path.exists():
        return [TextContent(type="text", text=f"错误：文件不存在 {file_path}")]
    if path.suffix.lower() != ".pdf":
        return [TextContent(type="text", text="错误：不是 pdf 文件")]

    doc = fitz.open(str(path))
    try:
        text_parts = []
        for page in doc:
            text = cast(str, page.get_text()).strip()
            if text:
                text_parts.append(text)
        combined = "\n".join(text_parts)
        if not combined:
            return [TextContent(type="text", text="未提取到可摘要的文本")]
        preview = combined[:max(length, 50)]
        return [TextContent(type="text", text=f"摘要预览：\n{preview}")]
    finally:
        doc.close()
