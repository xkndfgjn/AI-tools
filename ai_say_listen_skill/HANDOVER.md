# 交接文档：小雅语音助手（HanaAgent 语音对话壳）

> 目的：让未来任何一个会话/开发者 5 分钟内进入状态。**做了什么、没做什么、怎么接手，全在这里。**
> 最后更新：2026-09-07（阶段三框架验收通过）

---

## 0. 项目一句话

Windows 10 常驻语音助手壳：说「小雅小雅」唤醒 → 录音 → 转文字 → 分析层（分组/改口/强度打分）→ 净文本按思考强度提交给 Hana server → 拿回复 → TTS 播报。**独立于 HanaAgent 桌面界面，只要求 Hana server 后台运行。**

## 1. 设计来源（为什么长这样）

设计经过多轮讨论 + 外网文献验证，每个决策都有出处，别轻易推翻：

| 设计点 | 依据 |
|--------|------|
| 两级队列 + 分析层（收集/分析分离） | 学术 DTS「话语对连贯性评分」思路（SIGDIAL 2021, Xing & Carenini） |
| 净文本提交（改口作废再发，不边算边丢） | 批评预生成的「waste computation on predictions that must be rolled back」（LTS-VoiceAgent, arXiv 2601.19952）；本方案取更保守的「确认后提交」端点 |
| 强度打分 → 动态 thinking level | 学术 Adaptive Reasoning（arXiv 2511.10788）：按输入难度分配推理 effort，本方案属「推理时控制派」；Hana 的 thinking level 接口实测支持 off/minimal/low/medium/high/xhigh |
| 攒话合并窗口 burst_window | 用户提出的「3 秒间隔视为一次对话」工程化，默认 2.5s 可调 |
| 双线程解耦 | 监听（慢在录音/转写）与对话（慢在 Hana/TTS）互不阻塞；线程间只走 queue.Queue |

## 2. 状态总览

| 模块 | 状态 | 说明 |
|------|------|------|
| core/hana_client.py | ✅ 完成 | HTTP + WebSocket 全封装 + set_thinking_level + 撞车重试 |
| core/stt.py | ✅ 完成 | faster-whisper small（已下载），懒加载 |
| main.py record_audio | ✅ 完成 | RMS 静音检测录音（阶段一） |
| core/pipeline.py | ✅ 完成 | 两级队列 + 攒话合并 + 净文本提交 |
| core/analyzer.py | 🟡 最简版 | 规则版可用（词表/阈值全 config 必传校验）；语义版 TODO |
| core/listener.py | 🟡 可用 | wake 骨架恒真（免唤醒）；连续监听态未实现 |
| core/dialog.py | ✅ 完成 | 设 level → ask → TTS（tts 骨架，打印占位） |
| core/tts.py | ❌ 骨架 | 阶段四待实现 |
| core/wake.py | ❌ 骨架 | 阶段五待实现 |

## 3. 已完成的关键资产（交接重点）

### 3.1 Hana server 外部对话接口（已实测）
- 连接信息在 `C:\Users\<用户名>\.hanako\server-info.json`：`port` + `token`（**token 会轮换，每次启动重读，勿缓存**）
- HTTP：`http://127.0.0.1:{port}`，请求头 `Authorization: Bearer {token}`
  - `GET /api/health`、`GET /api/sessions`、`POST /api/sessions/new`（body `{}`）、`POST /api/sessions/switch`（body `{path}`）
- WebSocket：`ws://127.0.0.1:{port}/ws`（同鉴权头）
  - 发消息：`{"type":"prompt","text":...,"sessionId":...,"sessionPath":...}`
  - 收事件：`text_delta`（累积 delta）、`turn_end`（结束）、`error`、`status`、`mood_*`、`thinking_*`、`tool_*`
- 思考强度：`POST /api/session-thinking-level`，body `{"sessionPath":..., "level":"off|minimal|low|medium|high|xhigh"}`（DeepSeek 全支持）
- 会话单工：同一 agent 同时只能一个活跃 turn，撞车会返回 error「还在说话」→ hana_client 已内置重试（默认 3 次、间隔 3s）

### 3.2 环境与模型状态（本机现状）
- Python 3.11.9（D:\python3.11），已装：websocket-client、faster-whisper 1.2.1、sounddevice 0.5.6、numpy、ctranslate2
- small 模型已下载到 `~/.cache/huggingface`（HF 国内走镜像：`set HF_ENDPOINT=https://hf-mirror.com`）
- 参考/验证脚本（留在 D:\OH-WorkSpace，可删）：
  - `ws-probe.js`：接口连通性原型
  - `test_hana_client.py`：ask 单测
  - `test_stage1.py`：录音→转写→对话全链路实测
  - `accept_stage3.py`：阶段三框架验收（改口/打分/config/metadata）

### 3.3 配置结构（config.example.json）
- `pipeline.burst_window`（2.5s 攒话窗口）、`queue_one_max`、`queue_two_max`、
  `poll_interval`（0.5s 空闲轮询）、`put_timeout`（1.0s 背压等待）
- `analyzer.analyzer_mode`（rules/semantic 分派点）、四个词表、`default_effort`、
  `effort_bounds`（长度分档上界 {minimal/low/medium/high}）、`chitchat_max_len`
- `app.listen_timeout`（8s）、`silence_ratio`（1.2）、`wake_retry_delay`（1.0s）
- **Analyzer 构造参数全部必传（代码内无默认词表/阈值），改词表一律改 config.json 的 analyzer 段**
- 无 config.json 时用 config.py 的 DEFAULTS 兜底，不崩

## 4. 未完成清单（按接手优先级）

### ① 阶段四：TTS 播报（成本最低、收益最直接）
- 实现 `core/tts.py` 的 `speak(text)`：edge-tts 合成 mp3 → sounddevice 播放（需联网）
- 完成后 `main.py` 全链路闭环：真机语音 → 播报
- 注意：edge-tts 是微软在线接口；离线场景换 pyttsx3（本地系统 TTS）

### ② 阶段五：唤醒词（接上后才是真·常驻待机）
- 实现 `core/wake.py` 的 `wait_for_wakeword()` + `stop()`：pvporcupine（个人非商用免费）
- 中文唤醒词「小雅小雅」需 Picovoice 控制台生成 `.ppn`，放 `wake.keyword_path`
- **坑**：`stop()` 必须能打断阻塞中的 wait（listener.stop 依赖它）；`wait_for_wakeword` 要响应停止信号，否则 Ctrl+C 退出拖 5s
- 同时可做 `listener.py` 的连续监听态 TODO（唤醒后常驻采集、静音超阈值才回唤醒态）

### ③ 分析层语义逻辑（天花板最高，从最明显的体验瑕疵做起）
1. **语义级改口**（优先）：修「算了不用了」尾巴残留；识别无词表改口（「哦不对，我改主意了」）
2. **精细强度打分**：意图类型、句法复杂度、否定/条件结构、专有名词密度（替代长度+词表）
3. **语义级分组**：段间连贯性评分（embedding 余弦 / LLM），参考「话语对连贯性评分」（SIGDIAL 2021）。建议先做小实验对比 embedding 方案再定
- 全部走 `Analyzer.analyze()` 同一接口 + `analyzer_mode` 分派点，外部调用方不动

## 5. 已知问题与坑（接手前必读）

1. **改口尾巴残留**：`['查天气','算了不用了']` → 净文本「不用了」（应整块作废）。词表版局限，已知
2. **wake 骨架恒真**：现在是免唤醒模式，每录一段回唤醒态
3. **对话只打印不播报**：tts 骨架，回复不出声
4. **HF 缓存 symlink 警告**：Windows 正常现象，多占磁盘；可设 `HF_HUB_DISABLE_SYMLINKS_WARNING`
5. **HF 下载**：国内网络先 `set HF_ENDPOINT=https://hf-mirror.com`
6. **server 必须后台运行**：程序启动时读不到 server-info.json 会报 FileNotFoundError（桌面端开着即可）
7. **测试会话**：早期接口测试在 Hana 侧边栏留了几个测试会话（「收到」那几条），无害可删
8. **Analyzer 构造全必传**：词表/阈值无代码内默认值，直接 `Analyzer()` 会 ValueError；
   改词表/分档一律改 `config.json` 的 analyzer 段（这是解耦设计，不是 bug）

## 6. 快速上手（5 分钟进入状态）

```bat
cd D:\AI_Tools\AI_tools\ai_say_listen_skill
:: 1. 环境（本机已装好，新机器才需要）
python scripts\setup_env.py

:: 2. 配置
copy config.example.json config.json

:: 3. 验证 server 连通（Hana 桌面端需开着）
python main.py --text        :: 文本对话模式，不进监听，验证链路

:: 4. 真机语音（当前 tts 无声音，回复打印在控制台）
run.cmd
```

代码阅读顺序：`main.py`（编排）→ `pipeline.py`（数据流）→ `analyzer.py`（分析层）→ `listener.py` / `dialog.py`（两端线程）。

## 7. 后续建议

- 每完成一阶段跑 `python main.py` 真机联调一次
- 分析层语义逻辑接入前，先确认 `analyzer_mode` 分派点与 `AnalyzedBlock.metadata` 扩展字段用法
- 想验证完整语音闭环，优先做 TTS（第 4 节 ①），做完就是「能听会说」
