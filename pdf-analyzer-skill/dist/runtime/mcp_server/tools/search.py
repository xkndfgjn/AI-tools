from pathlib import Path
from typing import Any, cast

import fitz
from mcp.types import TextContent


def _extract_keywords(keywords: str | list[Any]) -> list[str]:
    """把传入的关键词（字符串或数组）统一转为去重后的非空字符串列表。"""
    if isinstance(keywords, str):
        items = [k.strip() for k in keywords.replace("，", ",").split(",") if k.strip()]
    else:
        items = [str(k).strip() for k in keywords if str(k).strip()]
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item and item.lower() not in seen:
            seen.add(item.lower())
            result.append(item)
    return result


async def pdf_search_keywords(
    file_path: str,
    keywords: str | list[Any],
    page_start: int = 0,
    page_end: int = -1,
) -> list[TextContent]:
    """在 PDF 中搜索关键词，返回命中的页码和上下文片段（大小写不敏感）。

    keywords 支持逗号分隔的字符串（如 "hello,world"）或字符串数组。
    """
    path = Path(file_path)
    if not path.exists():
        return [TextContent(type="text", text=f"错误：文件不存在 {file_path}")]
    if path.suffix.lower() != ".pdf":
        return [TextContent(type="text", text="错误：不是 pdf 文件")]

    kw_list = _extract_keywords(keywords)
    if not kw_list:
        return [TextContent(type="text", text="错误：未提供搜索关键词")]

    doc = fitz.open(str(path))
    try:
        total = doc.page_count
        if page_end == -1 or page_end >= total:
            page_end = total - 1
        if page_end < 0:
            page_end = 0
        if page_start < 0:
            page_start = 0
        if page_start > page_end:
            return [TextContent(type="text", text="错误：页码范围无效")]

        lower_kw = [k.lower() for k in kw_list]
        results: list[str] = []
        matched_pages: list[int] = []

        for idx in range(page_start, page_end + 1):
            page = doc.load_page(idx)
            text = cast(str, page.get_text())
            lower_text = text.lower()
            page_matches: list[str] = []

            for kw, lkw in zip(kw_list, lower_kw):
                pos = 0
                count = 0
                while True:
                    found = lower_text.find(lkw, pos)
                    if found == -1:
                        break
                    count += 1
                    start = max(found - 40, 0)
                    end = min(found + len(lkw) + 40, len(text))
                    snippet = text[start:end].replace("\n", " ").strip()
                    page_matches.append(f"  [{kw}] 匹配#{count}：...{snippet}...")
                    pos = found + len(lkw)

            if page_matches:
                matched_pages.append(idx)
                results.append(f"===== 第 {idx + 1} 页 =====")
                results.extend(page_matches)

        if not matched_pages:
            return [TextContent(type="text", text=f"未找到关键词：{', '.join(kw_list)}")]

        total_matches = sum(1 for r in results if "匹配#" in r)
        result_text = (
            f"搜索到 {total_matches} 处匹配，涉及 {len(matched_pages)} 页\n\n"
            + "\n".join(results)
        )
        return [TextContent(type="text", text=result_text)]
    finally:
        doc.close()
