import contextlib
import io

from mcp.server import MCPServer
from mcp.types import TextContent

# PyMuPDF 在 import fitz 时直接向 stdout 打印 deprecation 警告（C 层 print，
# 不走 warnings 模块）。这会污染 MCP stdio 协议流，因此在导入 fitz 相关
# 模块前临时重定向 stdout/stderr 到缓冲区。
_capture_out = io.StringIO()
_capture_err = io.StringIO()
with (
    contextlib.redirect_stdout(_capture_out),
    contextlib.redirect_stderr(_capture_err),
):
    from tools.extract import pdf_extract_text as extract_text_impl
    from tools.metadata import pdf_get_metadata as get_metadata_impl
    from tools.merge import pdf_merge as merge_impl
    from tools.split import pdf_split as split_impl
    from tools.summarize import pdf_summarize as summarize_impl

app = MCPServer("pdf-mcp-tool")


@app.tool()
async def pdf_extract_text(file_path: str, page_start: int = 0, page_end: int = -1) -> list[TextContent]:
    """提取PDF指定页码范围内的纯文本内容
    
    Args:
        file_path: PDF本地绝对路径
        page_start: 起始页码，从0开始，默认0
        page_end: 结束页码（包含），-1表示到最后一页，默认-1
    """
    return await extract_text_impl(file_path, page_start=page_start, page_end=page_end)


@app.tool()
async def pdf_get_metadata(file_path: str) -> list[TextContent]:
    """获取PDF元数据信息，包括作者、标题、总页数、创建时间等
    
    Args:
        file_path: PDF本地绝对路径
    """
    return await get_metadata_impl(file_path)


@app.tool()
async def pdf_split(file_path: str, output_file: str, page_start: int, page_end: int) -> list[TextContent]:
    """分割PDF，截取指定页码范围生成新的PDF文件
    
    Args:
        file_path: 源PDF绝对路径
        output_file: 输出新PDF的完整绝对路径
        page_start: 起始页码，从0开始
        page_end: 结束页码（包含）
    """
    return await split_impl(file_path, output_file, page_start, page_end)


@app.tool()
async def pdf_merge(input_pdf_list: list[str], output_file: str) -> list[TextContent]:
    """合并多个PDF文件，按列表顺序拼接，输出为单个新PDF
    
    Args:
        input_pdf_list: 待合并的PDF绝对路径数组，顺序即合并顺序
        output_file: 合并后输出PDF的完整绝对路径
    """
    return await merge_impl(input_pdf_list, output_file)


@app.tool()
async def pdf_summarize(file_path: str, length: int = 200) -> list[TextContent]:
    """对PDF全文生成简短摘要，减少大段内容直接占用上下文
    
    Args:
        file_path: PDF本地绝对路径
        length: 摘要目标字数，默认200
    """
    return await summarize_impl(file_path, length=length)


if __name__ == "__main__":
    # MCPServer.run() is synchronous and manages the stdio transport internally.
    app.run(transport="stdio")
