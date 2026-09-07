# 小雅语音助手（HanaAgent 语音对话壳）

Windows 10 常驻语音助手壳：听到唤醒词「小雅小雅」→ 录音 → 语音转文字（STT）→
**分析层**（分组 / 改口检测 / 强度打分）→ 净文本按思考强度（effort）提交给
Hana server 获取回复 → 文字转语音（TTS）播报。

整个壳独立于 HanaAgent 桌面界面运行，只要求 Hana server 在后台启动。

## 架构（阶段三：双线程 + 两级队列 + 分析层）

```
┌──────────────────────────────────────────────────────────────────────┐
│                        本程序（Python 3.11）                            │
│                                                                        │
│   ┌──────────────┐    ┌────────────────────────┐    ┌───────────────┐  │
│   │ 监听线程      │    │       分析层线程         │    │ 对话线程       │  │
│   │ ListenThread │    │  Pipeline.run_analyzer │    │ DialogThread  │  │
│   │              │    │                        │    │               │  │
│   │ wake 唤醒词   │    │  ① 攒话合并(burst_window)│    │ ② 取净文本块    │  │
│   │ record_audio │    │  ② Analyzer 分析        │    │ ③ 设 thinking  │  │
│   │ stt 转写      │    │    - 分组(合并成块)      │    │    level       │  │
│   └──────┬───────┘    │    - 改口检测(作废前文)  │    │ ④ client.ask   │  │
│          │            │    - 强度打分(effort)    │    │ ⑤ tts.speak    │  │
│          │ feed_segment(text)                   │    │               │  │
│          ▼            │                        │    │               │  │
│   ┌──────────────┐    │   ┌───────────────┐    │    │               │  │
│   │  队列一 QueueOne│──▶│   AnalyzedBlock  │───▶│    │               │  │
│   │  (文本段)       │    │  (净文本+effort)  │    │    │               │  │
│   └──────────────┘    │   └───────────────┘    │    │               │  │
│       收集队列          │        队列二 QueueTwo   │    │               │  │
│                        └────────────────────────┘    └───────┬───────┘  │
│                                                              │          │
│                                              HTTP /ws 带 Bearer 鉴权    │
│                                                              ▼          │
│                                                    ┌──────────────────┐ │
│                                                    │   Hana server     │ │
│                                                    │ 127.0.0.1:port    │ │
│                                                    │ /api/session-     │ │
│                                                    │  thinking-level   │ │
│                                                    │ /ws 对话           │ │
│                                                    └──────────────────┘ │
└──────────────────────────────────────────────────────────────────────┘

数据流：唤醒 → 录音(8s 上限) → 转写文本段 → 队列一 → 攒话合并/改口/打分
        → 净文本块 → 队列二 → 设 thinking level → WS 发 prompt → 累积 text_delta
        → turn_end 取完整回复 → TTS 播报 → 回到等待唤醒

线程与队列说明：
- 三个线程：监听线程（收话→转文本→投递）、分析层线程（队列一消费→攒话→分析）、
  对话线程（队列二消费→对话→播报）。监听与对话互不阻塞。
- 两级队列：队列一收集文本段（满时丢新段保麦克风不卡）；队列二收净文本块
  （满时分析层背压等待，对话是慢环节，背压优于丢请求）。
- 线程间通信只用 queue.Queue / threading.Event，不共享可变状态。
- 分析层语义级逻辑（语义分组 / 语义改口 / 精细打分）为 TODO，当前为
  「最简可运行版」（词表改口 + 长度/信号词打分），见 core/analyzer.py。
```

## 目录结构

```
ai_say_listen_skill/
├── README.md                # 本文件
├── requirements.txt         # 依赖声明（按模块分组注释）
├── config.example.json      # 配置样例（复制为 config.json 后修改）
├── core/
│   ├── __init__.py
│   ├── config.py            # 加载 config.json + server-info.json（port/token）
│   ├── hana_client.py       # ★已完成：HanaClient，HTTP + WebSocket 全封装
│   │                        #   + set_thinking_level（设置思考强度）
│   ├── stt.py               # 已完成：语音转文字（阶段一实现）
│   ├── tts.py               # 骨架：文字转语音（阶段四实现）
│   ├── wake.py              # 骨架：唤醒词检测（阶段五实现）
│   ├── analyzer.py          # ★阶段三新增：分析层（分组/改口/强度打分，最简版）
│   ├── pipeline.py          # ★阶段三新增：两级队列 + 净文本提交
│   ├── listener.py          # ★阶段三新增：常驻监听线程
│   └── dialog.py            # ★阶段三新增：对话线程（设 level → ask → TTS）
├── main.py                  # 主流程（双线程编排启动；--text 纯文本模式）
├── scripts/
│   ├── __init__.py
│   └── setup_env.py         # 环境引导：查 Python 版本 + pip 装依赖
└── run.cmd                  # Windows 一键启动
```

## 依赖

见 `requirements.txt`，按模块分组：

| 模块 | 依赖 | 用途 |
|------|------|------|
| 核心通信 | websocket-client | 与 Hana server 的 HTTP/WebSocket 通信（已用到） |
| 阶段一录音 | sounddevice, numpy | 采集麦克风音频 |
| 阶段二 STT | faster-whisper | 语音转文字（模型自动下载） |
| 阶段四 TTS | edge-tts | 文字转语音（在线合成，需联网） |
| 阶段五唤醒 | pvporcupine | 本地唤醒词检测 |

### Hana server 连接信息

Hana server 在后台运行时，会把当前 `port` 和 `token` 写到
`C:\Users\<用户名>\.hanako\server-info.json`。token 会轮换，因此
`core/config.py` 的 `load_server_info()` 每次启动都重新读取该文件，
**不要**把 port/token 写死在配置文件里。

## 使用方式

```bat
:: 1. 环境引导（首次）
python scripts\setup_env.py

:: 2. 复制配置并修改
copy config.example.json config.json

:: 3. 启动（要求 Hana server 已在后台运行）
run.cmd

:: 或纯文本对话模式（不启动监听/录音，保留阶段一可用性）
python main.py --text
```

## 阶段计划

### 阶段一：录音 + 转写（STT）✅ 已完成
- 依赖：`sounddevice`、`numpy`、`faster-whisper`
- `core/stt.py`：faster-whisper 懒加载 + 转写（16k float32，beam_size=5，vad_filter）
- `main.py record_audio()`：录音到静音（连续 1.2s）或 `listen_timeout` 秒，返回 float32 数组；
  静音阈值相对前 0.5s 背景音量（`app.silence_ratio`，默认 1.2）
- 模型：首次转写自动从 HuggingFace 下载；网络受限先 `set HF_ENDPOINT=https://hf-mirror.com`

### 阶段二：纯文本对话（HanaClient）✅ 已完成
- `core/hana_client.py`：HTTP（health / sessions）+ WebSocket（ask）全封装，
  含撞车重试（busy 重试 / 空回复重试），异常统一 `HanaClientError`（中文信息）

### 阶段三：双线程框架 + 两级队列 + 分析层 ✅ 框架完成（分析层语义级逻辑待实现）
- `core/pipeline.py`：`Pipeline`，队列一（收集文本段）/ 队列二（净文本块），
  `feed_segment(text)` 投递、`run_analyzer()` 攒话合并（burst_window=2.5s）与封口提交
- `core/analyzer.py`：`Analyzer.analyze(segments, last_ts) -> AnalyzedBlock | None`，
  三职责：分组（本轮=合并成块）/ 改口检测（词表版，命中后文保留前文作废）/
  强度打分（长度 + 信号词 → effort：off/minimal/low/medium/high/xhigh）
- `core/listener.py`：`ListenThread`，唤醒 → 录音 → 转写 → 投递队列一（不碰对话）
- `core/dialog.py`：`DialogThread`，队列二 → `set_thinking_level`（失败降级）→ `ask` → TTS
- `hana_client.set_thinking_level(session_path, level)`：POST /api/session-thinking-level
- 验证：`python main.py` 联调；`python main.py --text` 走纯文本对话
- **待实现（TODO）**：分析层语义级分组 / 语义级改口检测 / 精细强度打分，
  见 `core/analyzer.py` 内注释

**解耦设计（阶段三验收标准）**：
- 分析层可插拔：`Analyzer.analyze(segments, last_ts) -> AnalyzedBlock | None` 是稳定接口，
  三职责（分组/改口/打分）各自独立方法；`config.analyzer.analyzer_mode` 分派实现版本
  （`rules` 当前可用；`semantic` 同一接口换实现，未实现会抛 NotImplementedError），
  换算法不动 pipeline/监听/对话线程。
- 依赖注入：ListenThread / DialogThread / Pipeline / Analyzer 的依赖（client、stt、tts、
  wake、record_func、config 值）全部构造注入，模块内不 import 全局实例；
  换 STT/TTS/唤醒/监听策略只改 main.py 装配处。
- 线程间只经队列通信：队列一/队列二元素契约写在 core/pipeline.py 模块 docstring；
  业务线程只用 feed_segment / take_block 两个公开入口，不互相调内部方法。
- 监听三块可替换：listener.py 把唤醒检测（_wait_wakeword）/ VAD 切段（_capture_utterance）/
  STT 转写（_transcribe）拆成独立方法，各自委托注入对象，注释标明替换点。
- 零硬编码：词表、effort 分档阈值（effort_bounds）、chitchat_max_len、burst_window 等
  全部从 config 读（config.py DEFAULTS 兜底），analyzer 代码内无默认词表/魔法数字。
- 队列二契约可扩展：`AnalyzedBlock.metadata: dict`（可空）供语义分析器塞
  相关性分数/置信度，对话线程忽略该字段。

### 阶段四：TTS 播报
- 依赖：`edge-tts`
- 实现 `core/tts.py` 的 `speak(text)`：edge-tts 合成 mp3 后用 sounddevice 播放
  （注意：edge-tts 是微软在线接口，需要联网）。
- 验证：让程序把 `ask()` 的回复读出来。

### 阶段五：唤醒词
- 依赖：`pvporcupine`（个人/非商用免费）
- 实现 `core/wake.py` 的 `wait_for_wakeword()`：porcupine 打开麦克风流逐帧检测，
  命中「小雅小雅」返回 True。默认英文内置词可先用 `porcupine`，中文需
  Picovoice 控制台生成自定义 `.ppn` 文件放到 `wake.keyword_path`。
- 验证：常驻后台，说话唤醒→对话→播报，形成完整闭环。

每阶段完成后跑一遍 `python main.py` 联调。

## 实测验证状态（2026-09-07）

已真机验证过的链路：
- ✅ Hana server 外部对话接口（HTTP + WebSocket + Bearer token 鉴权）实测可通，
  参考一次性探测脚本 `D:\OH-WorkSpace\ws-probe.js`、`D:\OH-WorkSpace\test_hana_client.py`
- ✅ 录音 → faster-whisper small 转写 → 对话 → 回复，全链路实测通过（用户口述「帮我测试一下语音功能」转写准确）
- ✅ 连续快速对话撞车（「小雅还在说话」）重试机制实测通过
- ✅ 分析层逻辑（改口/打分/分组）单测通过，见 `D:\OH-WorkSpace\accept_stage3.py`
- ✅ small 模型已下载到本地 HF 缓存（~/.cache/huggingface），无需重复下载
- ⚠️ 双线程整体联调（真机语音跑通三线程）尚未做：需要 TTS 或至少以打印形式验证对话线程消费队列二

## 已知局限（暂未处理）

- 改口词表版：整段作废类表达（「算了不用了」）会把尾巴「不用了」误当净文本，
  留待语义级改口解决（core/analyzer.py TODO）
- wake 骨架恒真 = 免唤醒模式（每段录音后回唤醒态）；连续监听态（唤醒后常驻采集、
  静音超阈值才回唤醒）未实现（core/listener.py TODO）
- 对话线程目前只打印回复（tts 为骨架），未真正播报（阶段四）
- Windows 下 HF 缓存无 symlink 支持，模型缓存多占磁盘；可设 HF_HUB_DISABLE_SYMLINKS_WARNING 消除警告

详细交接见 `HANDOVER.md`。
