# WeChat RPA Skill

本地常驻 HTTP 服务，将微信桌面版操作封装为 REST API，供 AI Agent 调用。

> **当前状态**：架构已切换为**视觉优先**。新版微信（4.x，Qt 渲染）的 UIAutomation 控件树为空，已放弃控件树定位，改为 OCR（RapidOCR / PP-OCRv6，CPU，中文优先）+ 模板匹配 + 区域比例锚定。`open_chat`（按名打开联系人聊天窗）已可用并经单测验证；发消息 / 读消息等操作的输入框定位仍在推进。AI 视觉兜底接口已预留，暂未接入。

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 启动服务（必须在用户交互会话中运行，不能在沙箱/服务后台启动）
python src/main.py
# 或双击 scripts/start.bat

# 3. 验证
curl http://127.0.0.1:9420/health
```

## 文档

完整架构设计见 [HANDOFF.md](./HANDOFF.md)

## 技术路线

纯 RPA / Windows UI 自动化，模拟真人鼠标键盘操作。不 Hook 微信进程、不读数据库、不碰私有协议。

> **新版微信（Qt 渲染）注意事项**：4.x 微信用 Qt 自绘窗口（`ClassName = Qt51514QWindowIcon`），UIAutomation 钻不进去，控件树为空。因此本项目**放弃控件树定位，改为纯视觉**：OCR + 模板匹配 + 区域比例锚定。控件树策略保留为 legacy，默认关闭。

## 调试

- `GET /api/debug/ocr` — 全窗口 OCR 文本 + 坐标 dump。调 `open_chat` 区域参数（`config.yaml` 的 `search.*`）时：先在微信里按 `Ctrl+F` 搜个人，再调这个接口，看 OCR 认出什么、落在哪个坐标，据此校准 `box_height_px` / `result_width_ratio` / `result_height_px`。
- `GET /api/debug/control_tree` — 控件树 dump（Qt 微信下返回空属正常现象）。
