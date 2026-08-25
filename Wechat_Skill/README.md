# WeChat RPA Skill

本地常驻 HTTP 服务，将微信桌面版操作封装为 REST API，供 AI Agent 调用。

> **当前状态**：项目处于脚手架阶段。服务可启动，`/health` 与 `/api/operations` 可用，但 RPA 引擎与各操作（发消息、读消息等）尚未实现，调用 `/api/execute` 会返回 `failed`。详见 [ARCHITECTURE.md §12 开发计划](./ARCHITECTURE.md#12-开发计划)。

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

完整架构设计见 [ARCHITECTURE.md](./ARCHITECTURE.md)

## 技术路线

纯 RPA / Windows UI 自动化，模拟真人鼠标键盘操作。不 Hook 微信进程、不读数据库、不碰私有协议。
