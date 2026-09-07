# -*- coding: utf-8 -*-
"""
配置加载模块。

职责：
1. 加载项目根目录下的 config.json（若不存在则使用内置默认值）。
2. 读取 Hana server 的 server-info.json，获取最新 port 和 token。

说明：
- Hana server 的 token 会轮换，因此每次启动都要重新读取 server-info.json，
  不要缓存旧值。
- server-info.json 由 Hana server 生成，固定位于
  C:\\Users\\<用户名>\\.hanako\\server-info.json。
"""

import json
import os

# 项目根目录（core/ 的上一级）
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 用户配置文件路径（运行时读取，用户可编辑）
CONFIG_PATH = os.path.join(PROJECT_ROOT, "config.json")
# 配置样例路径（展示全部可配置项，复制为 config.json 后修改）
EXAMPLE_CONFIG_PATH = os.path.join(PROJECT_ROOT, "config.example.json")
# Hana server 信息文件路径（port / token 在此，每次启动重新读取）
SERVER_INFO_PATH = os.path.join(os.path.expanduser("~"), ".hanako", "server-info.json")

# 默认配置：config.json 缺失或某个字段缺失时使用
DEFAULTS = {
    "stt": {
        "model": "small",        # faster-whisper 模型档位：base / small / medium / large-v3
        "device": "auto",        # 计算设备：auto / cpu / cuda
        "language": "zh",        # 转写语言（None 表示自动检测）
        "sample_rate": 16000,    # 录音采样率（faster-whisper 期望 16k）
        "blocksize": 3200,       # sounddevice 每次读取的音频块大小（约 0.2s）
        "input_device": None,    # 录音设备序号（None 用系统默认麦克风）
    },
    "tts": {
        "voice": "zh-CN-XiaoxiaoNeural",  # edge-tts 音色
        "rate": "+0%",           # 语速，如 "+10%" / "-10%"
        "volume": "+0%",         # 音量，如 "+50%"
        "output_device": None,   # 播放设备序号（None 用系统默认）
    },
    "wake": {
        "keyword_path": None,    # pvporcupine 自定义唤醒词文件（.ppn），None 用内置英文词
        "sensitivity": 0.5,      # 唤醒灵敏度 0.0 ~ 1.0，越高越灵敏也越易误触发
    },
    "app": {
        "listen_timeout": 8,        # 唤醒后最长录音秒数
        "silence_ratio": 1.2,       # 静音判定阈值（相对背景音量的倍数）
        "response_timeout": 60,     # 等待 AI 回复的超时秒数
        "wake_retry_delay": 1.0,    # 唤醒检测异常后的重试间隔（秒）
    },
    "pipeline": {
        "burst_window": 2.5,     # 攒话合并窗口（秒）：段间间隔 ≤ 该值则并入同一块
        "queue_one_max": 50,     # 队列一容量（监听 → 分析），满时丢新段并告警
        "queue_two_max": 20,     # 队列二容量（分析 → 对话），满时分析层背压等待
        "poll_interval": 0.5,    # 分析层/对话线程的空闲轮询间隔（秒）
        "put_timeout": 1.0,      # 队列二满时背压等待的单次超时（秒）
    },
    "analyzer": {
        # 分析层模式：rules=规则版（当前实现）；semantic=语义版（embedding/LLM，后续接入）。
        # 同一 Analyzer 接口换实现，改动只发生在 core/analyzer.py 与这里的取值。
        "analyzer_mode": "rules",
        # 改口词：命中后该词及之前文本作废，只保留其后内容
        "revision_words": ["算了", "等等", "不对", "不是", "取消", "换一个", "还是说"],
        # 闲聊词：纯寒暄 → off/low（不需要思考）
        "chitchat_words": ["你好", "谢谢", "晚安", "再见"],
        # 危险词：涉及删/发/付/提交等操作 → xhigh（保守求稳）
        "danger_words": ["删除", "发送", "支付", "提交"],
        # 复杂词：分析/对比/方案等任务 → high
        "complex_words": ["分析", "对比", "方案", "总结", "解释"],
        # 无信号词时中段文本（17~60 字符）的默认档
        "default_effort": "medium",
        # 长度分档上界（字符数）：≤ minimal → minimal；≤ low → low；
        # ≤ medium → default_effort；≤ high → high；超过 high → xhigh
        "effort_bounds": {"minimal": 4, "low": 16, "medium": 60, "high": 200},
        # 命中闲聊词且整句 ≤ 该长度 → off（纯寒暄，不需要思考）；否则 → low
        "chitchat_max_len": 8,
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    """把 override 递归合并进 base，返回新 dict（不修改入参）。"""
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(path: str = None) -> dict:
    """加载 config.json，缺失字段用默认值补齐。

    参数:
        path: config.json 路径，默认取项目根目录下的 config.json。

    返回:
        合并后的完整配置 dict，结构见 DEFAULTS。
    """
    cfg_path = path or CONFIG_PATH
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                user_cfg = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"[config] 警告：读取 {cfg_path} 失败（{e}），改用默认配置")
            user_cfg = {}
    else:
        print(f"[config] 未找到 {cfg_path}，使用默认配置"
              f"（可参考 {EXAMPLE_CONFIG_PATH} 创建）")
        user_cfg = {}
    return _deep_merge(DEFAULTS, user_cfg)


def load_server_info(path: str = None) -> dict:
    """读取 server-info.json，返回至少包含 port / token 的 dict。

    参数:
        path: server-info.json 路径，默认 ~/.hanako/server-info.json。

    返回:
        {"port": int, "token": str, ...}（保留文件中的其余字段，便于排查）。

    异常:
        FileNotFoundError: 文件不存在（说明 Hana server 未启动）。
        ValueError: 文件缺少 port 或 token 字段（版本不兼容）。
    """
    info_path = path or SERVER_INFO_PATH
    if not os.path.exists(info_path):
        raise FileNotFoundError(
            f"找不到 Hana server 信息文件：{info_path}\n"
            "请确认 HanaAgent server 已在后台启动（桌面端打开即可）。"
        )
    with open(info_path, "r", encoding="utf-8") as f:
        info = json.load(f)
    if "port" not in info or "token" not in info:
        raise ValueError(
            f"{info_path} 缺少 port 或 token 字段，Hana server 版本可能不兼容"
        )
    return info
