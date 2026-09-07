# -*- coding: utf-8 -*-
"""
主流程（阶段三框架版）：加载配置 → 初始化各模块 → 双线程 + 两级队列编排启动。

线程分工：
- 监听线程（core.listener.ListenThread）：唤醒 → 录音 → STT → 投递队列一。
- 分析层线程（threading.Thread，跑 pipeline.run_analyzer）：消费队列一，
  攒话合并 → Analyzer 分析（分组/改口/打分）→ 净文本块进队列二。
- 对话线程（core.dialog.DialogThread）：消费队列二 → 设 thinking level →
  ask → TTS 播报。

当前状态：
- hana_client（含 set_thinking_level）已完成；stt 已完成；record_audio 已完成。
- tts / wake 为占位实现，各自打印占位日志，整体可运行。
- 分析层为「最简可运行版」（词表改口 + 长度/信号词打分），语义级逻辑见
  core/analyzer.py 的 TODO。
- 命令行参数 --text：纯文本对话模式（不启动监听/录音/线程），保留阶段一
  文本 ask 的可用性。

退出：Ctrl+C。
"""

import argparse
import threading
import time

from core.config import load_config, load_server_info
from core.hana_client import HanaClient
from core.stt import SpeechToText
from core.tts import TextToSpeech
from core.wake import WakeWordDetector
from core.analyzer import Analyzer
from core.pipeline import Pipeline
from core.listener import ListenThread
from core.dialog import DialogThread


def record_audio(duration: float, sample_rate: int, blocksize: int = 3200,
                 input_device: int = None, silence_ratio: float = 1.2):
    """录音到静音或超时，返回 float32 音频数组（16k 单声道）。

    参数:
        duration: 最长录音秒数（config.app.listen_timeout）。
        sample_rate: 采样率（config.stt.sample_rate，16k）。
        blocksize: sounddevice 每次回调的音频块大小（config.stt.blocksize，约 0.2s）。
        input_device: 录音设备序号（config.stt.input_device，None 用系统默认麦克风）。
        silence_ratio: 静音判定阈值，相对背景音量的倍数（config.app.silence_ratio）。

    返回:
        float32 一维 numpy 数组；录音失败或未采到有效语音时返回空数组。

    静音检测算法（相对阈值 + 提前结束，详见函数内常量与注释）：
        1. 预热期取前 0.5s 各块 RMS 的中位数作为背景基准 base_rms
           （唤醒后 0.5s 内通常安静；中位数比均值稳健，抗偶发噪声）。
        2. 某块 RMS 超过 max(base_rms * silence_ratio, 1e-3) 判定为语音，
           1e-3 是绝对下限，防止背景极安静时把微小声当语音误触发。
        3. 检测到语音后，连续静音满 1.2s 视为说话结束，提前收尾；
           从未检测到语音时，连续静音满 2.0s 直接放弃（无人说话，不干等）。
        4. 达到 duration 上限强制结束。
        5. 结束后校验：有效语音总时长不足 0.4s，视为误触发，返回空数组。

    说明：本函数保留在 main.py（阶段一完整实现，接口不变），通过参数注入
    ListenThread（见下），避免 core.listener 反向 import main 造成循环导入。
    """
    import threading
    import time

    import numpy as np

    try:
        import sounddevice as sd
    except ImportError:
        print("[record] 未安装 sounddevice，请先执行：python scripts/setup_env.py")
        return np.array([], dtype=np.float32)

    # ---- 算法常量（配合上方设计说明）----
    PRE_ROLL_SEC = 0.5      # 背景噪声估计窗口（前 0.5s）
    SILENCE_END_SEC = 1.2   # 检测到语音后，连续静音该时长即收尾
    LEAD_SILENCE_SEC = 2.0  # 从未检测到语音时，静音该时长即放弃
    MIN_SPEECH_SEC = 0.4    # 有效语音总时长下限，低于视为无效
    ABS_FLOOR = 1e-3        # 语音判定绝对下限（RMS 值）

    block_sec = blocksize / sample_rate  # 单个音频块的时长

    # 采集缓冲；callback 运行在 sounddevice 的音频线程，与主线程共享需加锁
    blocks: list = []    # 每块 float32 一维数组
    rms_list: list = []  # 每块的 RMS 能量
    lock = threading.Lock()

    def _callback(indata, frames, time_info, status):
        """音频回调：拷贝当前块并计算 RMS。status 非空仅说明缓冲抖动，不影响数据。"""
        block = np.asarray(indata[:, 0], dtype=np.float32).copy()  # 取单声道
        block_rms = float(np.sqrt(np.mean(block * block)))
        with lock:
            blocks.append(block)
            rms_list.append(block_rms)

    # 打开麦克风（失败时给中文提示并返回空数组，不打断主流程）
    stream = None
    try:
        stream = sd.InputStream(samplerate=sample_rate, blocksize=blocksize,
                                channels=1, dtype="float32", device=input_device,
                                callback=_callback)
        stream.start()
    except Exception as e:
        print(f"[record] 打开麦克风失败：{e}（input_device={input_device}）")
        if stream is not None:
            try:
                stream.close()
            except Exception:
                pass
        return np.array([], dtype=np.float32)

    try:
        # 主循环：轮询采集进度，按结束条件退出
        while True:
            with lock:
                n = len(rms_list)
            elapsed = n * block_sec
            if elapsed >= duration:
                break  # 达到录音上限，强制结束

            if n >= 1:
                # 阈值 = 预热期 RMS 中位数 × silence_ratio，且不低于绝对下限
                pre_roll_n = max(1, int(PRE_ROLL_SEC / block_sec))
                with lock:
                    base_rms = float(np.median(rms_list[:pre_roll_n]))
                threshold = max(base_rms * silence_ratio, ABS_FLOOR)

                # 定位最后一个语音块，计算其后的连续静音时长
                with lock:
                    snapshot = list(rms_list)
                last_voice = -1
                for i, r in enumerate(snapshot):
                    if r > threshold:
                        last_voice = i
                silence_sec = (n - 1 - last_voice) * block_sec

                if last_voice < 0:
                    if elapsed >= LEAD_SILENCE_SEC:
                        break  # 一直没说话，提前放弃
                elif silence_sec >= SILENCE_END_SEC:
                    break  # 说话结束，提前收尾

            time.sleep(0.05)  # 轮询间隔，远小于一个音频块（0.2s）
    finally:
        try:
            stream.stop()
        finally:
            stream.close()

    # 后置校验：有效语音总时长不足则视为未采到有效声音，返回空数组
    with lock:
        collected = list(blocks)
        collected_rms = list(rms_list)
    total_sec = len(collected) * block_sec
    pre_roll_n = max(1, int(PRE_ROLL_SEC / block_sec))
    base_rms = float(np.median(collected_rms[:pre_roll_n])) if collected_rms else 0.0
    threshold = max(base_rms * silence_ratio, ABS_FLOOR)
    speech_sec = sum(1.0 for r in collected_rms if r > threshold) * block_sec
    if total_sec < PRE_ROLL_SEC or speech_sec < MIN_SPEECH_SEC:
        print(f"[record] 未采到有效语音（总 {total_sec:.1f}s / 语音 {speech_sec:.1f}s），放弃")
        return np.array([], dtype=np.float32)

    audio = np.concatenate(collected) if collected else np.array([], dtype=np.float32)
    print(f"[record] 采到 {total_sec:.1f}s 音频（语音约 {speech_sec:.1f}s）")
    return audio


def _init_common(cfg, info):
    """初始化各模块（client/stt/tts/wake），供两种模式共用。"""
    client = HanaClient(info["port"], info["token"],
                        timeout=cfg["app"]["response_timeout"])
    stt = SpeechToText(model=cfg["stt"]["model"], device=cfg["stt"]["device"],
                       language=cfg["stt"]["language"], sample_rate=cfg["stt"]["sample_rate"])
    tts = TextToSpeech(voice=cfg["tts"]["voice"], rate=cfg["tts"]["rate"],
                       volume=cfg["tts"]["volume"], output_device=cfg["tts"]["output_device"])
    wake = WakeWordDetector(keyword_path=cfg["wake"]["keyword_path"],
                            sensitivity=cfg["wake"]["sensitivity"])
    return client, stt, tts, wake


def main_text_mode(cfg, info, client) -> None:
    """纯文本对话模式（--text）：单轮文本 ask，不启动监听/录音/线程。

    保留阶段一「纯文本对话」的可用性：输入回车发送，exit/quit 退出。
    只依赖 hana_client，不需要麦克风/扬声器。
    """
    print("===== 文本对话模式（--text，不启动监听）=====")
    print("输入内容回车发送给 Hana，输入 exit / quit 退出。")
    while True:
        try:
            text = input("你 > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not text:
            continue
        if text.lower() in ("exit", "quit", "退出"):
            break
        try:
            reply = client.ask(text)
        except Exception as e:
            print(f"[error] 对话失败：{e}")
            continue
        if not reply:
            print("[error] 回复为空")
            continue
        print(f"小雅 > {reply}")
    print("[exit] 文本模式退出")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="小雅语音助手（HanaAgent 语音对话壳）")
    parser.add_argument("--text", action="store_true",
                        help="纯文本对话模式：不启动监听/录音，直接文本 ask（保留阶段一可用性）")
    args = parser.parse_args()

    print("======== 小雅语音助手（HanaAgent 语音壳）========")

    # 1. 加载配置与 server 信息
    cfg = load_config()
    info = load_server_info()  # 每次启动重新读取，token 会轮换
    print(f"[config] Hana server 已就绪：port={info['port']}, token长度={len(info['token'])}")

    # 2. 初始化各模块
    client, stt, tts, wake = _init_common(cfg, info)

    # 纯文本模式：不进线程编排，直接单轮对话
    if args.text:
        main_text_mode(cfg, info, client)
        return

    # 3. 分析层 + 两级队列（依赖全部显式装配，换实现只改这里）
    analyzer = Analyzer(
        analyzer_mode=cfg["analyzer"]["analyzer_mode"],
        revision_words=cfg["analyzer"]["revision_words"],
        chitchat_words=cfg["analyzer"]["chitchat_words"],
        danger_words=cfg["analyzer"]["danger_words"],
        complex_words=cfg["analyzer"]["complex_words"],
        default_effort=cfg["analyzer"]["default_effort"],
        effort_bounds=cfg["analyzer"]["effort_bounds"],
        chitchat_max_len=cfg["analyzer"]["chitchat_max_len"],
    )
    pipeline = Pipeline(
        analyzer=analyzer,
        burst_window=cfg["pipeline"]["burst_window"],
        queue_one_max=cfg["pipeline"]["queue_one_max"],
        queue_two_max=cfg["pipeline"]["queue_two_max"],
        poll_interval=cfg["pipeline"]["poll_interval"],
        put_timeout=cfg["pipeline"]["put_timeout"],
    )

    # 4. 双线程 + 分析层线程（线程间只用队列/Event 通信，契约见 core/pipeline.py）
    listen = ListenThread(
        pipeline=pipeline, stt=stt, wake=wake, record_func=record_audio,
        listen_timeout=cfg["app"]["listen_timeout"],
        sample_rate=cfg["stt"]["sample_rate"],
        blocksize=cfg["stt"]["blocksize"],
        input_device=cfg["stt"]["input_device"],
        silence_ratio=cfg["app"]["silence_ratio"],
        wake_retry_delay=cfg["app"]["wake_retry_delay"],
    )
    dialog = DialogThread(pipeline=pipeline, client=client, tts=tts,
                          poll_interval=cfg["pipeline"]["poll_interval"])
    analyzer_thread = threading.Thread(
        target=pipeline.run_analyzer, name="analyzer", daemon=True)

    print("[init] 模块初始化完成，启动监听（Ctrl+C 退出）")

    try:
        # 5. 启动三个线程
        analyzer_thread.start()
        listen.start()
        dialog.start()
        print("[init] 监听/分析/对话线程已启动")

        # 6. 主线程保活，等待 Ctrl+C（KeyboardInterrupt）
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        print("\n[exit] 收到退出信号，正在优雅停止……")
    finally:
        # 7. 优雅退出：先停监听（不再投递）→ 分析层排空 → 对话线程
        listen.stop()
        listen.join(timeout=5)
        pipeline.stop()  # 投递哨兵，分析层消费完剩余段后退出
        analyzer_thread.join(timeout=5)
        dialog.stop()
        dialog.join(timeout=5)
        print("[exit] 已退出")


if __name__ == "__main__":
    main()
