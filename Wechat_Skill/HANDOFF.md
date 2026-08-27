# WeChat RPA Skill — 交接文档

> 面向接手本项目的 AI / 开发者。读完本文即可上手继续开发，无需重新摸索。

最后更新：2026-08-27 · 阶段：**open_chat / send_message 已端到端验证可用，read_messages 已实测可读**，其余操作待验证/改造。

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
引擎层   src/main.py           OperationEngine: 加载 config / 初始化 controller+finder+watcher / 串行锁执行
操作层   src/operations/        每个 operation = 一个类 + @register_operation，自动发现
         ├─ contacts.py        open_chat, list_sessions
         ├─ send_message.py
         ├─ read_messages.py
         ├─ send_file.py
         ├─ _helpers.py        open_chat(核心) / estimate_chat_region / ocr_extract_text / sleep_ms
         ├─ base.py            BaseOperation / OperationContext / OperationResult
         └─ registry.py        @register_operation
RPA 层    src/rpa/
         ├─ controller.py      原子操作：找窗口/激活/点击/键盘/截图（全同步，asyncio.to_thread 调用）
         ├─ ocr_engine.py      RapidOCR 单例封装（核心）
         ├─ finder.py         策略链 finder（当前业务基本不直接用，见 §9）
         ├─ screenshot.py      截图/保存
         └─ watcher.py         窗口状态后台轮询
配置     config/config.yaml     server / wechat / rpa / search / chat_region / finder / logging
测试     tests/                 test_api.py(3) + test_open_chat.py(2) = 5 passed
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
# 期望: {"status":"ok","wechat_running":true,"wechat_window":"HWND:...","window_rect":[...],"operations_count":5}
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

> 写诊断脚本时也务必 `open(path,"w",encoding="utf-8")` 写 JSON，再 `cat`，避免终端乱码。

## 6. 操作现状表（接手第一眼重点）

| 操作 | 状态 | 说明 |
|---|---|---|
| `open_chat` | ✅ **已验证可用** | 纯视觉流程，API 端到端测过打开「文件传输助手」聊天，OCR 标题确认。见 §7。 |
| `send_message` | ✅ **已验证可用** | = `open_chat` + `type_text`(剪贴板粘贴) + `Enter`。已实际发送到「文件传输助手」和「老妈」，发送后的微信截图均显示绿色消息气泡。 |
| `read_messages` | 🟡 **已实测但仍是半成品** | 已对「老妈」真实读取成功，能识别聊天消息；已通过 `chat_region.*` 排除左侧会话列表和底部输入框，但结果仍混入时间、聊天记录卡片和截断文本。 |
| `send_file` | 🟡 待验证 | = `open_chat` + `Ctrl+Shift+F` + 路径 + Enter×2。`Ctrl+Shift+F` 是否仍是新版文件快捷键**未验证**。 |
| `list_sessions` | 🟡 半成品 | 先试控件树(Qt 必空)再 OCR 左侧栏。OCR 能列出会话名但混入时间/预览噪声，无解析去噪。 |

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

`read_messages` 使用 `config/config.yaml` 的 `chat_region.*` 截取聊天内容区：默认从窗口左侧 45%、顶部 12% 开始，到右侧 99%、底部 79% 结束。该区域已实测能排除左侧会话列表和底部输入框，但仍会包含聊天区内的时间标签、聊天记录卡片等非消息文本。

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

### finder（`src/rpa/finder.py`）— 当前基本闲置
- 策略链 `template_match -> ocr`（`control_tree` 已注释移除，`ai_vision` 是 stub）。
- 业务代码（open_chat 等）**不直接用 finder**，而是直接 `OcrEngine + 坐标计算`。finder 是给未来"按 FindTarget 通用定位"留的接口。
- ⚠️ `finder.py` 顶部 docstring 仍写"control tree first"，**已过时**，接手时可顺手改。
- `config/templates/` 目录空（只有 .gitkeep），TemplateMatchStrategy 暂无模板可用。

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

每个 operation 的 `run()` 会自动 `pre_hook`(前截图) + `execute` + `post_hook`(后截图)，截图存 `data/screenshots/`，路径挂在返回的 `screenshots` 里。**验证操作是否成功**：取 `screenshots[-1]`(后截图) OCR 看结果。

## 11. 待办优先级（建议顺序）

1. **`read_messages` 结果清洗**：聊天区域边界已通过 `chat_region.*` 调整完成，当前重点是过滤时间标签和聊天记录卡片，并按消息气泡的空间关系合并被 OCR 拆开的多行消息。2026-08-27 对「老妈」复测得到 13 条 OCR 文本，后截图见 `data/screenshots/wechat_1787823143301529300.png`。

2. **发送后的结果校验**：当前 `send_message` 的 success 表示动作链执行完成；如需更强保证，可在后截图中 OCR 校验刚发送的文本或消息气泡。

3. **`send_file` 验证 `Ctrl+Shift+F`**：手动试这个快捷键是否打开文件选择框，不行就改用点击"+"菜单的文件入口（需 OCR 找入口）。

4. **`list_sessions` 去噪解析**：会话项是「头像+名字+时间+预览」多行，需把每项的几行聚类成一条会话（按 y 间距分组），只取名字行。

5. 顺手：改 `finder.py` 过时 docstring；按需补 `config/templates/` 模板。

## 12. 已知坑 & 约束

- **Windows bash 中文**：见 §5，curl 不可用，用 Python urllib。
- **坐标**：OCR 坐标都是**图像局部**，点击前务必换算成屏幕绝对（窗口左上 + ROI 偏移 + OCR 中心）。换算错就点错地方。
- **窗口可被移动**：每次操作前 `activate_window` + `get_window_rect` 重新拿坐标，别缓存 rect。
- **首次 OCR 慢**：模型首次加载 1–2s，API 超时给足（urllib `timeout=90`）。
- **控件树不可用**：别再指望 `find_control`，一切走 OCR/坐标。
- **搜索候选排序**：见 §7，联想项在联系人上方，必须「精确/最短优先」而非「最靠上」。
- **Ctrl+F 假设**：open_chat 假设 Ctrl+F 是搜索快捷键，已在当前版本验证可用；微信改键位时这里会断。
- **测试**：`test_open_chat.py` 用合成图 + 真 OcrEngine 测候选选择逻辑；改 open_chat 选择策略后跑 `pytest tests/ -q` 应 5 passed。

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

四项全绿 = open_chat / send_message 基线完好，read_messages 已可用但仍需按 §11 第 1 步精化。
