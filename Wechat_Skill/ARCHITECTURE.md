# WeChat RPA Skill — 架构设计文档

> 面向 HanaAgent 的微信桌面端 RPA 能力框架。本地常驻 HTTP 服务，将微信操作封装为 REST API。
>
> **说明**：本文档为设计稿，项目当前处于脚手架阶段，多数模块为 TODO / 占位实现。已完成与未完成情况见 [§12 开发计划](#12-开发计划)。

## 1. 项目定位

| 项 | 说明 |
|---|---|
| 技术路线 | 纯 RPA / Windows 原生 UI 自动化，模拟真人鼠标键盘 |
| 不做什么 | 不 Hook 微信进程、不读数据库、不碰私有协议、不依赖商业服务 |
| 服务对象 | HanaAgent（通过 exec_command → Invoke-RestMethod 调用） |
| 运行环境 | Windows + 微信桌面版 ≥ 4.1.7，Python 3.11+ |

## 2. 设计目标

1. **高扩展性**：新增微信操作（发朋友圈、群管理、加好友）只需新建一个文件 + 装饰器注册，不碰核心代码
2. **策略可插拔**：UI 元素定位策略（模板匹配 / OCR / AI 视觉）可独立替换或链式降级
3. **错误自愈**：操作级重试 + 窗口级监控 + 服务级守护
4. **人在回路**：关键操作支持操作前后截图、人工确认拦截
5. **零外部依赖**：不需要激活码、不绑定任何商业服务

## 3. 技术栈

| 组件 | 选型 | 用途 |
|---|---|---|
| HTTP 框架 | fastapi + uvicorn | REST API 服务 |
| UI 自动化 | uiautomation | 窗口查找、激活、控件树遍历 |
| 图像匹配 | opencv-python | 模板匹配定位图标/按钮 |
| OCR | easyocr | 屏幕文字识别定位动态元素 |
| 截图 | pillow (ImageGrab) | 窗口/全屏截取 |
| 输入模拟 | ctypes (Win32 API) | 鼠标移动/点击/键盘 |
| 配置 | pyyaml | YAML 配置读写 |
| 日志 | loguru | 结构化日志 |

## 4. 三层架构

```
┌──────────────────────────────────────────────┐
│                API Layer (REST)               │
│  FastAPI routes → dispatch to OperationRegistry│
└───────────────────┬──────────────────────────┘
                    │
┌───────────────────▼──────────────────────────┐
│           Operation Layer (插件化)            │
│  BaseOperation + @register_operation          │
│  send_message / read_messages / send_file     │
│  contacts / moments / mass_sending / ...      │
└───────────────────┬──────────────────────────┘
                    │
┌───────────────────▼──────────────────────────┐
│              RPA Engine Layer                │
│  Controller (window/mouse/keyboard)          │
│  Finder (template → ocr → ai-vision 链)       │
│  Screenshot | Watcher                        │
└───────────────────┬──────────────────────────┘
                    │
               ┌────▼────┐
               │ 微信桌面端 │
               └─────────┘
```

**各层职责边界：**

- **API Layer**：接收 HTTP 请求，解析参数，路由到对应 Operation，返回 JSON。不含任何 RPA 逻辑。
- **Operation Layer**：每个操作是一个独立类，编排"先做什么、再做什么"的业务流程（如发消息 = 搜索联系人 → 点进聊天 → 输入文字 → 回车）。通过 Registry 自动注册。
- **RPA Engine Layer**：提供原子能力（点坐标、输入文字、截图、找元素），不含业务逻辑。Operation 调用 Engine 完成具体动作。

## 5. 扩展机制

### 5.1 操作插件化

```python
# 新增一个操作只需两步：
# 1. 继承 BaseOperation 实现 execute()
# 2. 用装饰器注册

@register_operation("send_message")
class SendMessageOperation(BaseOperation):
    description = "Send text message to a contact or group"

    async def execute(self, ctx: OperationContext, params: dict) -> OperationResult:
        # ctx.controller → 鼠标键盘窗口
        # ctx.finder → 元素定位
        # ctx.config → 配置
        # ctx.logger → 日志
        ...
        return OperationResult(status=OperationStatus.SUCCESS, data={...})
```

Registry 在 `operations/__init__.py` 中通过自动导入所有模块完成注册。新增文件放入 `operations/` 目录即自动被发现。

### 5.2 定位策略可插拔

```python
class FindStrategy(ABC):
    @abstractmethod
    def find(self, screenshot: np.ndarray, target: FindTarget) -> Optional[Element]:
        ...

class ElementFinder:
    """链式降级：先试策略 A，失败试 B，再失败试 C。"""

    def __init__(self, strategies: list[FindStrategy]):
        self._strategies = strategies

    def find(self, screenshot, target) -> Optional[Element]:
        for s in self._strategies:
            if not s.supports(target):
                continue
            el = s.find(screenshot, target)
            if el:
                return el
        return None
```

内置三种策略，可按需增减：

| 策略 | 适用场景 | 原理 |
|---|---|---|
| TemplateMatchStrategy | 固定图标（搜索按钮、发送按钮） | OpenCV matchTemplate |
| OCRStrategy | 动态文字（联系人名、消息内容） | EasyOCR 识别文字拿坐标 |
| AIVisionStrategy | 复杂场景兜底 | 截图发 LLM 描述位置 |

### 5.3 Hook 系统

每个操作执行前后有 hook 点，可用于截图审计、人工确认、日志记录：

```python
class BaseOperation:
    async def pre_hook(self, ctx, params):
        """默认：操作前截图，保存为文件并记录路径"""
        ctx.screenshots.append(ctx.controller.save_screenshot())

    async def post_hook(self, ctx, params, result):
        """默认：操作后截图，保存为文件并记录路径"""
        ctx.screenshots.append(ctx.controller.save_screenshot())
```

子类可覆盖 pre_hook 实现人工确认拦截（`requires_confirmation = True` 时 API 层会先返回 `NEEDS_CONFIRMATION`，等用户确认后才执行）。

## 6. 核心接口定义

### 6.1 OperationContext

```python
@dataclass
class OperationContext:
    controller: RpaController     # 原子操作能力
    finder: ElementFinder          # 元素定位
    config: dict                  # 配置快照
    logger: loguru.Logger         # 日志
    screenshots: list = field(default_factory=list)  # 操作过程截图
```

### 6.2 OperationResult

```python
class OperationStatus(Enum):
    SUCCESS = "success"
    FAILED = "failed"
    NEEDS_CONFIRMATION = "needs_confirmation"

@dataclass
class OperationResult:
    status: OperationStatus
    data: Any = None
    message: str = ""
    screenshots: list[str] = field(default_factory=list)  # 截图文件路径列表
    duration_ms: int = 0
```

### 6.3 RpaController 关键方法

```python
class RpaController:
    def find_wechat_window(self) -> Optional[int]           # 查找微信窗口句柄
    def activate_window(self) -> bool                        # 激活/置顶微信窗口
    def get_window_rect(self) -> Optional[tuple[int,int,int,int]]  # (l,t,r,b)
    def click(self, x: int, y: int) -> None                 # 绝对坐标点击
    def double_click(self, x: int, y: int) -> None
    def right_click(self, x: int, y: int) -> None
    def drag(self, x1, y1, x2, y2, duration=0.5, steps=20) -> None
    def type_text(self, text: str) -> None                   # 剪贴板粘贴（中文可靠）
    def press_keys(self, *keys: str) -> None                 # 按键组合 (Ctrl, f)
    def screenshot(self, region=None) -> np.ndarray          # 截屏
    def save_screenshot(self, image=None, region=None) -> str  # 截图存盘，返回文件路径
    def _delay(self, ms=None) -> None                        # 按 action_delay_ms 延时
    def screen_to_window(self, x, y) -> tuple[int, int]      # 屏幕坐标 → 窗口坐标
    def window_to_screen(self, x, y) -> tuple[int, int]      # 窗口坐标 → 屏幕坐标
```

### 6.4 FindTarget / Element

```python
@dataclass
class FindTarget:
    """定位描述：可以是图片路径、文字、或坐标。"""
    template: Optional[str] = None    # 模板图片路径
    text: Optional[str] = None        # 要找的文字
    text_contains: bool = True       # 模糊匹配
    region: Optional[tuple] = None   # 限定搜索区域 (l,t,r,b)

@dataclass
class Element:
    x: int        # 屏幕绝对坐标
    y: int
    width: int
    height: int
    confidence: float    # 匹配置信度
    strategy: str        # 哪个策略找到的
```

## 7. REST API 设计

```
GET  /health
     → { "status": "ok", "wechat_running": true, "wechat_window": "...",
         "window_rect": [l,t,r,b], "operations_count": 5 }

GET  /api/operations
     → { "operations": [{"name": "send_message", "description": "..."}, ...] }

POST /api/execute
     Body: { "operation": "send_message", "params": { "to": "文件传输助手", "text": "你好" } }
     → { "status": "success", "data": {...}, "screenshots": [...], "duration_ms": 1234 }

POST /api/execute/confirm      # （规划中，尚未实现）
     Body: { "task_id": "xxx" }   # 确认执行一个 requires_confirmation 的操作

GET  /api/screenshot          # （未实现，当前返回 501）
     → image/png（当前微信窗口截图）

POST /api/screenshot/analyze  # （未实现，当前返回 501）
     Body: { "prompt": "当前聊天窗口里最新一条消息是什么" }
     → { "analysis": "...", "screenshot_path": "..." }
```

## 8. 并发控制

微信窗口只有一个，同一时间只能执行一个操作。所有操作通过 `asyncio.Lock` 串行化：

```python
class OperationEngine:
    def __init__(self):
        self._lock = asyncio.Lock()

    async def execute(self, op_class, params) -> OperationResult:
        op = op_class()
        ctx = OperationContext(controller=..., finder=..., config=..., logger=...)
        async with self._lock:
            return await op.run(ctx, params)
```

## 9. 错误处理与自愈

### 9.1 操作级重试

```python
@retry(max_attempts=3, backoff=1.0)
async def _do_something():
    ...
```

### 9.2 窗口级监控

`Watcher` 定期（每 10s）检查：
- 微信进程是否存活
- 微信窗口是否可见
- 窗口是否卡死（截图前后对比）

异常时尝试自动恢复（重新激活窗口），恢复失败则标记服务降级。

### 9.3 服务级守护

用 NSSM 或 Windows 计划任务将 Python 服务注册为开机自启 + 崩溃重启。

## 10. 配置结构

```yaml
# config/config.yaml
server:
  host: "127.0.0.1"
  port: 9420

wechat:
  window_name: "微信"
  process_name: "Weixin"
  version: "4.1.x"        # 仅记录，不影响逻辑

rpa:
  screenshot_dir: "./data/screenshots"
  template_dir: "./config/templates"
  ocr_languages: ["ch_sim", "en"]
  ocr_gpu: false
  template_threshold: 0.8
  action_delay_ms: 300    # 每个操作步之间的默认延迟
  retry:
    max_attempts: 3
    backoff: 1.0

finder:
  strategy_chain:        # 链式降级顺序
    - template_match
    - ocr
    # - ai_vision        # 可选，需要配置 LLM endpoint

logging:
  level: "INFO"
  file: "./data/logs/wechat_rpa.log"
  rotation: "10 MB"
```

## 11. 目录结构

```
Wechat_Skill/
├── ARCHITECTURE.md              ← 本文件
├── README.md
├── requirements.txt
├── config/
│   ├── config.yaml
│   └── templates/               # OpenCV 模板图片（搜索按钮、发送按钮等）
├── data/
│   ├── logs/
│   └── screenshots/
├── src/
│   ├── __init__.py
│   ├── main.py                  # FastAPI 启动入口
│   ├── api/
│   │   ├── __init__.py
│   │   ├── routes.py             # REST 路由
│   │   └── schemas.py            # Pydantic 请求/响应模型
│   ├── rpa/
│   │   ├── __init__.py
│   │   ├── controller.py         # 核心 RPA 控制器
│   │   ├── finder.py             # 元素定位（策略链）
│   │   ├── screenshot.py         # 截图工具
│   │   └── watcher.py            # 窗口状态监控
│   ├── operations/
│   │   ├── __init__.py           # 自动导入注册
│   │   ├── base.py               # BaseOperation + OperationContext + OperationResult
│   │   ├── registry.py           # 注册中心
│   │   ├── send_message.py       # 发文本消息
│   │   ├── send_file.py          # 发文件/图片
│   │   ├── read_messages.py      # 读聊天记录
│   │   └── contacts.py           # 联系人/搜索/打开聊天
│   └── utils/
│       ├── __init__.py
│       ├── logger.py             # loguru 日志配置
│       └── retry.py              # 重试装饰器
├── scripts/
│   ├── start.bat                # 启动服务（用户交互会话运行）
│   └── install.bat              # 安装依赖
└── tests/
    └── test_api.py
```

> 注：`data/logs/` 与 `data/screenshots/` 为运行时自动创建，仓库中仅保留占位 `.gitkeep`，并已被 `.gitignore` 忽略。

## 12. 开发计划

### Phase 1：核心框架（基础设施）
- [ ] RpaController：窗口查找/激活、鼠标键盘、截图
- [ ] ElementFinder + TemplateMatchStrategy + OCRStrategy
- [ ] OperationRegistry + BaseOperation + OperationContext
- [ ] FastAPI 基础路由 + Schemas
- [ ] 配置文件加载
- [ ] 日志系统
- [ ] 重试装饰器
- [ ] 启动/安装脚本

### Phase 2：基础操作
- [ ] send_message：发文本消息（搜索联系人 → 进聊天 → 粘贴 → 回车）
- [ ] read_messages：读聊天记录（截图聊天区域 → OCR 提取）
- [ ] contacts：搜索联系人、打开指定聊天
- [ ] send_file：发文件/图片（拖拽或 Ctrl+Shift+F）

### Phase 3：增强功能
- [ ] send_voice：发语音（需 VB-Cable）
- [ ] moments：发朋友圈
- [ ] mass_sending：批量群发
- [ ] group_summary：群聊总结（拉取消息 → AI 总结）
- [ ] auto_add_friend：自动通过好友请求

### Phase 4：稳定性
- [ ] Watcher 窗口监控 + 自愈
- [ ] 操作级重试完善
- [ ] 开机自启（NSSM / 计划任务）
- [ ] 单元测试
- [ ] 异常场景覆盖（微信未登录、窗口最小化、弹窗拦截等）

## 13. HanaAgent 集成方案

服务启动后（`http://127.0.0.1:9420`），HanaAgent 通过 PowerShell 调用：

```powershell
# 发消息
Invoke-RestMethod -Uri "http://127.0.0.1:9420/api/execute" -Method POST `
  -ContentType "application/json" `
  -Body '{"operation":"send_message","params":{"to":"文件传输助手","text":"你好"}}'

# 读最新消息
Invoke-RestMethod -Uri "http://127.0.0.1:9420/api/execute" -Method POST `
  -ContentType "application/json" `
  -Body '{"operation":"read_messages","params":{"chat":"项目群","limit":20}}'
```

未来可封装为 SKILL.md，让 Agent 自动识别用户意图并调用对应操作。
