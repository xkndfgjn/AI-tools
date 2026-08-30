# WeChat RPA Skill — 交接文档

> 面向接手本项目的 AI / 开发者。读完本文即可上手继续开发，无需重新摸索。

最后更新：2026-08-29 · 阶段：**`open_chat` / `send_message` / `send_file` / `read_messages` / `list_sessions` 已端到端验证可用；`broadcast_message` 群发已实现（默认开启短风控间隔，纯函数单测覆盖） OCR 去噪与会话项分组，返回稳定结构 `{name, preview, time, source, confidence}`，已在侧边栏真实截图场景下稳定收敛。**send_file 使用纯 SIFT 特征值匹配，已在调整窗口尺寸后向「文件传输助手」和「老妈」真实发送图片成功；其余扩展项待验收/改造。新增 `src/mcp.py` 提供 `SkillMcpFacade`（agent 对外工具入口；已通过 `OperationEngineTransport` 桥接到真实 OperationEngine，6 个 operation 注册为 tool，`POST /api/mcp/call` 端到端验证 open_chat）；`finder.py` 三处过时 docstring 已清理。

---

## 1. 项目目标

为**新版 Qt 渲染的微信桌面端（4.x，class_name=`Qt51514QWindowIcon`）**提供 HTTP RPA 能力：打开聊天、发消息、读消息、发文件、列会话。

## 2. 为什么要视觉方案（背景，必读）

新版微信用 Qt 重绘，**UIAutomation 控件树完全为空**——`data/control_tree.json` 实测 `"count": 0, "controls": []`。窗口本身能被 UIA 找到（它是顶层控件），但窗口内**没有任何子控件**暴露。所以：

- 所有基于控件树的定位（`find_control` / `find_controls_info`）在 Qt 微信上**必然返回空**。
- 整个项目的定位策略改为**纯视觉**：OCR（RapidOCR）+ 模板匹配。控件树代码保留但业务不再依赖。

旧版微信（`WeChatMainWndForPC`）控件树可用，但本项目**已全面转向新版**，旧路径仅作兼容残留。

## 3. 架构总览

```
HTTP 层   src/api/routes.py     /health /api/execute /api/operations /api/screenshot /api/debug/ocr ...
MCP 层   src/mcp.py            SkillMcpFacade / ToolRegistry / McpSessionManager（agent 对外工具入口；call() 唯一公开 API，call_tool() 故意 raise 强制走 facade；_DefaultMcpTransport no-op，测试用 FakeTransport。当前仅骨架，未与 operations 打通）
引擎层   src/main.py           OperationEngine: 加载 config / 初始化 controller+finder+watcher / 串行锁执行
操作层   src/operations/        每个 operation = 一个类 + @register_operation，自动发现
         ├─ contacts.py        open_chat, list_sessions
         ├─ send_message.py
         ├─ broadcast_message.py  群发：多目标串行 + 风控间隔（_broadcast.py 纯函数）
         ├─ read_messages.py
         ├─ send_file.py
         ├─ _helpers.py        open_chat(核心) / estimate_chat_region / ocr_extract_text / sleep_ms
         ├─ _message_parser.py  read_messages 清洗：时间戳关联为消息 time 字段 / 系统 / 聊天记录卡片 / 噪声过滤 + 多行气泡合并（纯函数，单测覆盖）
         ├─ _broadcast.py       broadcast_message 纯函数：targets 归一化/去重 + 风控间隔规划（单测覆盖）
         ├─ base.py            BaseOperation / OperationContext / OperationResult
         └─ registry.py        @register_operation
RPA 层    src/rpa/
         ├─ controller.py      原子操作：找窗口/激活/点击/键盘/截图（全同步，asyncio.to_thread 调用）
         ├─ ocr_engine.py      RapidOCR 单例封装（核心）
         ├─ finder.py         策略链 finder（当前业务基本不直接用，见 §9）
         ├─ screenshot.py      截图/保存
         └─ watcher.py         窗口状态后台轮询
配置     config/config.yaml     server / wechat / rpa / search / chat_region / finder / logging
测试     tests/                 test_api.py(3) + test_open_chat.py(2) + test_send_file.py(3) + test_read_messages.py(27) + test_list_sessions.py(2) + test_broadcast.py(11) + test_mcp_proxy.py(4) + test_mcp_transport.py(4) + test_mcp_api.py(3) = 59 passed
```

## 4. 运行

```bash
# 安装依赖（已装过，列出备查）
pip install -r requirements.txt

# 启动服务（前台，看日志）
python src/main.py
# 或后台（Windows git bash）
nohup python src/main.py > data/logs/server.log 2>&1 & disown

# 健康检查
curl http://127.0.0.1:9420/health
# 期望: {"status":"ok","wechat_running":true,"wechat_window":"HWND:...","window_rect":[...],"operations_count":6}
```

- 端口 `9420`，仅 `127.0.0.1`。
- `reload=False`，**改代码后必须重启服务**才生效。
- 启动时 `OcrEngine` 懒加载，**首次 OCR** 才下载/加载 ONNX 模型（约 1–2 秒），之后缓存。
- 微信窗口可最小化，`activate_window` 会用 `SW_RESTORE` 恢复并前置（已验证）。

## 5. 调用约定（重要：Windows 中文编码坑）

Windows bash 默认 GBK，**`curl` 带 JSON 中文会乱码导致 400**。请用 Python `urllib` + UTF-8：

```python
import json, urllib.request
req = urllib.request.Request(
    "http://127.0.0.1:9420/api/execute",
    data=json.dumps({"operation":"open_chat","params":{"name":"文件传输助手"}},
                    ensure_ascii=False).encode("utf-8"),
    headers={"Content-Type":"application/json"}, method="POST")
print(json.loads(urllib.request.urlopen(req, timeout=90).read().decode("utf-8")))
```

发送文字消息时，将请求参数改为 `{"operation":"send_message","params":{"to":"老妈","text":"发送消息测试"}}`。真实发送前必须确认联系人和消息内容；返回 `status: "success"` 后，应检查 `screenshots[-1]` 是否出现绿色消息气泡。

群发：`{"operation":"broadcast_message","params":{"targets":["老妈","文件传输助手"],"text":"群发测试"}}`。默认每条间隔 ~500-800ms 防风控（`interval_ms=0` 可关）；结果 `data` 含 `sent`/`failed` 列表与 `partial` 标志。

> 写诊断脚本时也务必 `open(path,"w",encoding="utf-8")` 写 JSON，再 `cat`，避免终端乱码。

## 6. 操作现状表（接手第一眼重点）

| 操作 | 状态 | 说明 |
|---|---|---|
| `open_chat` | ✅ **已验证可用** | 纯视觉流程，API 端到端测过打开「文件传输助手」聊天，OCR 标题确认。见 §7。 |
| `send_message` | ✅ **已验证可用** | = `open_chat` + `type_text`(剪贴板粘贴) + `Enter`。已实际发送到「文件传输助手」和「老妈」，发送后的微信截图均显示绿色消息气泡。 |
| `read_messages` | ✅ **已清洗可用** | 已对「老妈」真实读取并完成结果清洗：时间标签不再丢弃而是关联为后续消息的 `time` 字段（如 `16:11`/`昨天18:20`，一个时间戳对其后所有 live message 生效直到下一个时间戳）/ 折叠「聊天记录」卡片 / 单字噪声过滤，并按 y 间距+x 重叠合并多行气泡。2026-08-29 端到端验证 13 块 OCR → 3 条真实消息（老妈你回不回来吃饭@16:11 → 回来@16:11 → 发送消息测试@17:24），无时间/历史/噪声泄漏。message 结构为 `{content, confidence, time}`，无前置时间戳时 `time=null`。清洗逻辑在 `src/operations/_message_parser.py`（纯函数）。 |
| `send_file` | ✅ **纯特征值匹配，已端到端验证** | 先恢复并确认微信前台，再从当前窗口截图底部工具栏 ROI 中加载 `config/templates/wechat_file_button_features.npz` 的 SIFT 特征值，使用 BFMatcher/KNN 比率筛选和 RANSAC 单应性计算按钮中心，再将窗口局部坐标转换为屏幕绝对坐标点击。完全不使用 OCR 或固定比例兜底；特征匹配失败直接停止，避免把路径发成文字。已在窗口尺寸调整后向「文件传输助手」和「老妈」发送 JPG 成功。 |
| `list_sessions` | ✅ **已稳定化** | 直接 OCR 左侧栏；已按 y 方向分组会话项，过滤固定标签/时间/系统噪声，并返回稳定结构 `{name, preview, time, source, confidence}`。 |
| `broadcast_message` | ✅ **已实现（未真机端到端）** | 串行 `open_chat + type + Enter` 逐个发送，默认开启短风控间隔（`interval_ms=500` + `jitter_ms=300` 抖动，最后一条不等）。参数：`targets`(list 或单 str，自动去重保序)/`text`/`interval_ms`/`jitter_ms`/`max_targets`(>0 上限保护)/`stop_on_fail`。返回 `sent`/`failed`/`count`/`total`/`partial`。纯函数 `normalize_targets`/`plan_delays` 单测覆盖；待真机多联系人实测。 |

## 7. open_chat 核心流程（已验证，改它要懂这套）

文件：`src/operations/_helpers.py`

```
1. activate_window()                       # 恢复+前置微信
2. Ctrl+F -> Ctrl+A -> type_text(name)     # 打开搜索、清空、输入
3. sleep settle_ms(1200)                    # 等搜索结果刷新
4. screenshot(窗口rect) -> crop ROI         # ROI 见 §8
5. OcrEngine.extract(ROI) -> 候选           # 双向子串匹配 name in text or text in name
6. 选候选:                                  # ← 关键，见下
     exact 匹配(text==name)优先,取最靠上;
     否则 len(text) 最小优先(联系人名短)
7. click(屏幕绝对坐标) -> sleep 500ms
```

**为什么候选选择不是「最靠上」**：Ctrl+F 浮层从上到下是 ①搜一搜联想项（"文件传输助手打开/已读功能/怎么恢复…"）②真联系人(纯名) ③聊天记录匹配("…与文件传输助手的聊天记录")。联想项排在最上面，按「最靠上」会点到搜一搜而非联系人。**实测踩过这个坑**，已修为「精确优先，否则最短文本优先」。

## 8. 搜索区域几何 & 坐标换算（调参必读）

`config/config.yaml` 的 `search.*`：

| 参数 | 默认 | 含义 |
|---|---|---|
| `box_height_px` | 90 | 顶部搜索输入框高度，ROI 从这以下开始（跳过输入框里的词） |
| `result_width_ratio` | 0.40 | 结果区占窗口宽度比例（左 40%） |
| `result_height_px` | 600 | 结果区最大高度 |
| `settle_ms` | 1200 | 输入后等结果刷新的毫秒 |

ROI（窗口相对，像素）：`roi = screenshot[box_h : min(600,height), 0 : int(width*0.40)]`

**坐标换算**（OCR 给的是 ROI 内坐标，要转屏幕绝对再点击）：
```
screen_x = window_left + res_left(0) + ocr_center_x
screen_y = window_top  + res_top(box_h) + ocr_center_y
```
其中 `ocr_center_x` 是列方向中心、`ocr_center_y` 是行方向中心（相对 ROI 左上）。

**调参方法**：在微信里手动 Ctrl+F 输个名字，然后 `GET /api/debug/ocr`，看全窗口 OCR 结果和坐标，据此调 `search.*`。

`read_messages` 使用 `config/config.yaml` 的 `chat_region.*` 截取聊天内容区：默认从窗口左侧 45%、顶部 12% 开始，到右侧 99%、底部 79% 结束。该区域已实测能排除左侧会话列表和底部输入框，但仍会包含聊天区内的时间标签（现解析为消息 `time` 字段而非丢弃）、聊天记录卡片等非消息文本。

## 9. 关键模块细节

### OcrEngine（`src/rpa/ocr_engine.py`，核心）
- 进程级单例：`OcrEngine.get(config)`，`.reset()` 清除（测试用）。
- `engine.extract(image) -> list[dict]`，image 可为 ndarray / 文件路径。
- 返回项：`{text, confidence, box:[[x,y]×4角], center_x, center_y, width, height}`。无文字时返回 `[]`。
- 底层 RapidOCR（PP-OCRv6，CPU，onnxruntime），中文识别置信度 0.99+。模型在 `D:\python3.11\Lib\site-packages\rapidocr\models\`。

### RpaController（`src/rpa/controller.py`）
- 全部方法**同步阻塞**，async 上下文用 `await asyncio.to_thread(controller.xxx, ...)` 调。
- 可用：`find_wechat_window() -> HWND|None`、`activate_window() -> bool`、`get_window_rect() -> (l,t,r,b)|None`、`click(x,y)`、`type_text(s)`(剪贴板粘贴，CJK 可靠)、`press_keys(*keys)`(如 `press_keys("Ctrl","f")`、`press_keys("Enter")`)、`screenshot(region=None)->BGR ndarray`、`save_screenshot(...)`。
- **legacy 不依赖**：`find_control`/`find_all_controls`/`find_controls_info`（Qt 微信返回空，仅 `list_sessions` 试调后走 OCR fallback）。
- `_ensure_com()` 在每个公共方法里 CoInitialize，线程本地。

### finder（`src/rpa/finder.py`）- 当前基本闲置
- 策略链 `template_match -> ocr`（config `finder.strategy_chain` 默认值；`control_tree` 在 config 里注释关闭，但 `ControlTreeStrategy` 类仍保留在代码中供旧版微信兼容，`ai_vision` 是 stub）。
- 业务代码（open_chat 等）**不直接用 finder**，而是直接 `OcrEngine + 坐标计算`。finder 是给未来「按 FindTarget 通用定位」留的接口。
- ✅ 模块头 / `FindTarget` 的 `Control-tree fields (preferred)` / `ControlTreeStrategy` 的 `Primary strategy` 三处 docstring 已于 2026-08-29 改为「视觉优先」措辞，删除「control tree first」。
- `config/templates/` 目录只有 `wechat_file_button_features.npz` + .gitkeep，TemplateMatchStrategy 暂无模板（send_file 自带 npz 不走 finder）。

### SkillMcpFacade（`src/mcp.py`）- agent 对外工具入口（已桥接，2026-08-30）
- `SkillMcpFacade.call(tool_name, params) -> ToolResponse{ok, tool, result, message}` 是 agent 调用工具的**唯一公开 API**，**async**（桥接到 async OperationEngine）。构造时自动 `connect(session_id="skill-facade")`。
- `call_tool()` 方法被故意 `raise RuntimeError("Skill facade blocks direct MCP tool access...")`，强制走 facade 边界。
- `OperationEngineTransport(engine)` 是真实传输：`async call_tool(name, params)` 内 `OperationRegistry.get(name)` 取 operation 类，`await engine.execute(op_class, params)`，`OperationResult` 经 `_operation_result_to_dict` 序列化为 `{status,data,message,screenshots,duration_ms}`。未知 tool `raise ValueError("Unknown operation/tool: '...'")`。
- `build_default_facade(engine)` 工厂注册 6 个 operation 为 tool（`_register_default_tools`）。required_fields：`send_message`=[to,text]、`send_file`=[to,file_path]、`broadcast_message`=[targets,text]；`open_chat`(name/to/chat 别名)、`read_messages`(chat/to)、`list_sessions` 为 [] 留给 operation 自校验。
- `ToolRegistry.validate()` 校验必填字段，缺则 `ValueError: Tool '...' missing required fields: [...]`；未知 tool 静默放行，在 transport 报 ValueError。
- `McpSessionManager` 管理 connect/disconnect/`call_tool`（未 connect 时 `RuntimeError: MCP session is not connected`）；`McpConnectionState` 暴露 `connected/session_id/last_error/tool_count`。`_DefaultMcpTransport` 仍是 no-op，供测试/脚手架使用。
- **HTTP 入口**：`POST /api/mcp/call` `{"tool","params"}` -> `await facade.call()`（跑 uvicorn loop）；`GET /api/mcp/tools` 列已注册 tool。未知 tool -> 404，缺必填字段 -> 400。使用示例见 §5（把 `operation` 换成 `tool`、路径 `/api/mcp/call`）。
- 测试：test_mcp_proxy.py(4, async) facade 转发/call_tool 被禁/required_fields/list_tools；test_mcp_transport.py(4) transport 解析+序列化/未知 tool/注册 6 tool/required_fields；test_mcp_api.py(3) 路由列表/未知 tool 404/缺字段 400。

### main.py startup（已修）
- startup 里 `find_wechat_window` 被 `asyncio.wait_for(..., timeout=5.0)` + try-except 包住，**UIA 偶发阻塞不会卡死启动**。探测失败非致命（open_chat 内部自己 activate 查窗口）。
- watcher 后台轮询窗口状态，不阻塞 startup。
- 执行串行锁：`OperationEngine._lock`，微信单窗口，操作排队执行。

## 10. API 端点

| 方法 路径 | 用途 |
|---|---|
| `GET /health` | 服务+微信窗口状态 |
| `GET /api/operations` | 列出已注册操作 |
| `POST /api/execute` | 执行操作：`{"operation":"...","params":{...}}`，返回含 `screenshots`(前后截图路径)、`duration_ms` |
| `GET /api/screenshot` | 当前微信窗口 PNG |
| `POST /api/screenshot/analyze` | AI 视觉分析（501 未实现） |
| `GET /api/debug/control_tree` | 控件树 dump（Qt 微信返回空，基本无用） |
| `GET /api/debug/ocr` | **全窗口 OCR dump（调参主力）** |
| `GET /api/mcp/tools` | 列出 Skill facade 注册的 MCP tool（6 个 operation） |
| `POST /api/mcp/call` | 通过 facade 调工具：`{"tool":"...","params":{...}}`，内部桥接到 OperationEngine.execute；未知 tool 404、缺必填字段 400 |

每个 operation 的 `run()` 会自动 `pre_hook`(前截图) + `execute` + `post_hook`(后截图)，截图存 `data/screenshots/`，路径挂在返回的 `screenshots` 里。**验证操作是否成功**：取 `screenshots[-1]`(后截图) OCR 看结果。

## 11. 待办优先级（建议顺序）

> **当前未完成**：§11.2 `broadcast_message` 真机多目标端到端验证、§11.3 `send_message` 发送后结果校验。其余均已完成（§11.6 finder docstring 清理、§11.7 mcp facade 桥接均已完成）。

1. **`read_messages` 结果清洗**（已完成，2026-08-29）：`src/operations/_message_parser.py` 实现纯函数清洗：①时间标签（`16:11`/`昨天18:20`/`星期一`/`2026-8-27`/`下午3:00`）正则识别后**保留为后续消息的 `time` 字段**（不再丢弃），一个时间戳对其后所有 live message 生效直到下一个时间戳；②折叠「聊天记录」卡片——从 `XX的聊天记录` 标题到裸 `聊天记录` 标签之间全部归 history，`Name:` 前缀行兼底兜底；③单字符且 height > 2×正常行高（排除单字块后的均值）的噪声过滤；④同气泡多行按 y 间距≤0.6 合并行高且 x 区间重叠合并（合并后气泡取首块 `time`）。端到端对「老妈」截图验证 13→3（消息带 `time`：老妈你回不回来吃饭/回来@16:11、发送消息测试@17:24）。`read_messages` 返回新增 `filtered` 统计与 `raw_ocr_blocks` 计数；`limit` 现作用于清洗后的 message；message 结构为 `{content, confidence, time}`，无前置时间戳时 `time=null`。测试 `tests/test_read_messages.py` 27 例（含真实 fixture `tests/fixtures/ocr_mama_chat.json`）。后截图见 `data/screenshots/wechat_1787823143301529300.png`，OCR dump 脚本 `scripts/dump_ocr.py`。

2. **`broadcast_message` 真机端到端验证**（已实现，待真机）：`src/operations/broadcast_message.py` 串行发多目标，纯函数 `normalize_targets`（去重保序、None/空安全）/`plan_delays`（最后一条 0、抖动）在 `tests/test_broadcast.py` 11 例覆盖；缺参/max_targets 超限返回 FAILED。默认 `interval_ms=500`+`jitter=300` 短间隔（单条总耗时主要来自 open_chat ~2.5s，间隔只占 0.5-0.8s，`interval_ms=0` 可关）。待向多个真实联系人群发实测并核对 `data.partial` 与每条 `sent/failed`。

3. **发送后的结果校验**：当前 `send_message` 的 success 表示动作链执行完成；如需更强保证，可在后截图中 OCR 校验刚发送的文本或消息气泡。

4. **`send_file` 已完成端到端实测**：当前使用 `config/templates/wechat_file_button_features.npz` 做纯 SIFT 特征值匹配。特征库只保存关键点、描述子、按钮中心和尺寸，不保存原始图片；窗口尺寸调整后已实测仍可定位并发送。测试文件为 `C:\Users\21477\OneDrive\Desktop\36af47c7219c21fbc346d0d23bfd66d6.jpg`。

5. **`list_sessions` 去噪解析**（已完成，2026-08-29）：会话项是「头像+名字+时间+预览」多行，已按 y 间距分组同一条会话，过滤固定标签、时间、系统噪声，保留 `name` / `preview` / `time` / `source` / `confidence` 结构，`parse_session_entries()` 纯函数化并单测覆盖。

6. ✅ **已完成（2026-08-29）**：`finder.py` 三处过时 docstring（模块头 / `FindTarget` 的 `Control-tree fields (preferred)` / `ControlTreeStrategy` 的 `Primary strategy`）已改为「视觉优先」措辞。按需补 `config/templates/` 模板仍待办。

7. ✅ **已完成（2026-08-30）**：`src/mcp.py` SkillMcpFacade 已桥接到真实 OperationEngine。新增 `OperationEngineTransport`（`call_tool` 内 `OperationRegistry.get(name)` + `await engine.execute(op_class, params)`，OperationResult 序列化为 dict）；`build_default_facade(engine)` 注册 6 个 operation 为 tool（required_fields：send_message=[to,text]、send_file=[to,file_path]、broadcast_message=[targets,text]，open_chat/read_messages/list_sessions=[] 留给 operation 自校验别名）。链路改 **async**（engine 的 asyncio.Lock 绑定 uvicorn loop，同步阻塞会死锁）。新增 `POST /api/mcp/call` + `GET /api/mcp/tools` 路由；`await facade.call()` 跑在 uvicorn 同一 loop。端到端实测 `open_chat` 文件传输助手经 facade 返回 success（duration ~7.3s，含前后截图）。测试 test_mcp_proxy.py(4, async) + test_mcp_transport.py(4) + test_mcp_api.py(3)。

## 12. 已知坑 & 约束

- **Windows bash 中文**：见 §5，curl 不可用，用 Python urllib。
- **坐标**：模板匹配返回的是窗口截图内的局部坐标，点击前务必换算成屏幕绝对（窗口左上 + ROI 偏移 + 模板中心）。换算错就点错地方。
- **窗口可被移动**：每次操作前 `activate_window` + `get_window_rect` 重新拿坐标，别缓存 rect。
- **首次 OCR 慢**：模型首次加载 1–2s，API 超时给足（urllib `timeout=90`）。
- **控件树不可用**：别再指望 `find_control`；`open_chat` 等动态文本操作仍走 OCR，但 `send_file` 文件图标完全走模板匹配，不走 OCR。
- **send_file 特征匹配**：特征库位于 `config/templates/wechat_file_button_features.npz`，只保存 SIFT 特征值，不保存原始图像。截图 ROI 使用窗口相对比例，匹配点通过 RANSAC 单应性变换计算按钮中心，点击前必须加上窗口左上角转换为屏幕绝对坐标。特征匹配不到时必须失败，不能回退到猜测坐标。
- **搜索候选排序**：见 §7，联想项在联系人上方，必须「精确/最短优先」而非「最靠上」。
- **Ctrl+F 假设**：open_chat 假设 Ctrl+F 是搜索快捷键，已在当前版本验证可用；微信改键位时这里会断。
- **测试**：`test_open_chat.py` 用合成图 + 真 OcrEngine 测候选选择逻辑；`test_send_file.py` 覆盖特征匹配坐标和模型缺失保护；`test_read_messages.py` 27 例覆盖时间关联/卡片折叠/多行合并/噪声过滤；`test_list_sessions.py` 2 例覆盖会话去噪与分组；`test_broadcast.py` 11 例覆盖 targets 归一化/去重/None 安全 + 风控间隔规划。当前 `pytest tests/ -q` 已验证为 48 passed。

## 13. 30 秒自检（接手后第一步）

```bash
# 1. 服务在不在
curl -s http://127.0.0.1:9420/health
# 2. open_chat 还能不能用（用 python urllib，见 §5）
#    调 open_chat 文件传输助手，看 status==success
# 3. 测试还过不过
python -m pytest tests/ -q
# 4. read_messages 真实测试时，确认 status==success 并检查 screenshots[-1]
```

四项全绿 = open_chat / send_message 基线完好，read_messages 已完成结果清洗（§11.1），list_sessions 已完成去噪分组（§11.5），broadcast_message 已实现待真机验证（§11.2），可用。
