from typing import Any

from mcp.server import Server

from tools.extract import pdf_extract_text as extract_text_impl
from tools.metadata import pdf_get_metadata as get_metadata_impl
from tools.merge import pdf_merge as merge_impl
from tools.split import pdf_split as split_impl
from tools.summarize import pdf_summarize as summarize_impl

app = Server("pdf-skill")


def _register_tool(func: Any, *, name: str, description: str) -> None:
    setattr(app, "tool", getattr(app, "tool"))


async def pdf_extract_text(file_path: str, page_start: int = 0, page_end: int = -1) -> str:
    return (await extract_text_impl(file_path, page_start=page_start, page_end=page_end))[0].text


async def pdf_get_metadata(file_path: str) -> str:
    return (await get_metadata_impl(file_path))[0].text


async def pdf_split(file_path: str, output_file: str, page_start: int, page_end: int) -> str:
    return (await split_impl(file_path, output_file, page_start, page_end))[0].text


async def pdf_merge(input_pdf_list: list[str], output_file: str) -> str:
    return (await merge_impl(input_pdf_list, output_file))[0].text


async def pdf_summarize(file_path: str, length: int = 200) -> str:
    return (await summarize_impl(file_path, length=length))[0].text


_register_tool(pdf_extract_text, name="pdf_extract_text", description="读取本地PDF，提取页面文本，支持指定页码范围；传入文件绝对路径")
_register_tool(pdf_get_metadata, name="pdf_get_metadata", description="获取PDF元数据，作者、标题、页数等")
_register_tool(pdf_split, name="pdf_split", description="分割PDF，截取指定页码范围生成新PDF文件；page_start/page_end从0开始")
_register_tool(pdf_merge, name="pdf_merge", description="合并多个PDF文件，按列表顺序拼接，输出新PDF")
_register_tool(pdf_summarize, name="pdf_summarize", description="对PDF文本生成简短摘要，减少大段内容直接进入上下文")


if __name__ == "__main__":
    from mcp.server.stdio import stdio_server
    import asyncio

    async def main() -> None:
        async with stdio_server() as streams:
            await app.run(streams[0], streams[1], app.create_initialization_options())

    asyncio.run(main())
