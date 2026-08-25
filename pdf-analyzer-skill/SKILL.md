- PDF Analyzer

  调用入口：`python <skill_dir>/runtime/proxy.py <tool> "<json>"`，输出纯文本 stdout。

  ## Tools

  **1. pdf_txt — 提取文本**

  ```
  python .../proxy.py pdf_txt {"fp":"C:/a.pdf","pr":"1-3"}
  ```

  - fp 必填：PDF绝对路径
  - pr 可选：页码，1起始，如 "1-3" 或 "5"，省略=全文
  - ocr 预留，未启用

  **2. pdf_sum — 摘要**

  ```
  python .../proxy.py pdf_sum {"fp":"C:/a.pdf","len":200}
  ```

  - fp 必填；len 可选：目标字数，默认 200

  **3. pdf_search — 关键词搜索**

  ```
  python .../proxy.py pdf_search {"fp":"C:/a.pdf","kw":"hello,world","pr":"1-3"}
  ```

  - fp、kw 必填（kw 逗号分隔多个）；pr 可选

  ## 踩坑记录

  - **PowerShell 直传 JSON 会拆坏引号**（报"缺少 kw"/"不是 pdf 文件"）→ 用 python subprocess 包装 `json.dumps(args)` 传参
  - **沙箱拦 MCP 子进程管道**（WinError 5）→ 走提权；或直连 `tools/` 下函数（extract/summarize/search，async，返回 list[TextContent]），venv python + asyncio.run 即可，绕过 MCP
  - **只读环境设 `PYTHONDONTWRITEBYTECODE=1`**，防 import 写 __pycache__ 被拒
  - **fitz 弃用警告正常**，不影响功能

  ## 扩展

  元数据/分割/合并见 `runtime/mcp_server/pdf_engine.py`。新增工具：engine 加 `@app.tool()` + proxy.py TOOL_MAP 登记。
