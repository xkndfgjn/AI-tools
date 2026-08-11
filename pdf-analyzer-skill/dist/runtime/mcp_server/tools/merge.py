from pathlib import Path

import fitz
from mcp.types import TextContent


async def pdf_merge(input_pdf_list: list[str], output_file: str) -> list[TextContent]:
    """合并多个 PDF 文件。"""
    out_path = Path(output_file)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    new_doc = fitz.open()
    try:
        for fpath in input_pdf_list:
            p = Path(fpath)
            if not p.exists():
                return [TextContent(type="text", text=f"错误：待合并文件不存在 {fpath}")]
            sub_doc = fitz.open(str(p))
            try:
                new_doc.insert_pdf(sub_doc)
            finally:
                sub_doc.close()
        new_doc.save(str(out_path))
        return [TextContent(type="text", text=f"合并完成，输入文件数:{len(input_pdf_list)}，输出:{output_file}")]
    finally:
        new_doc.close()
