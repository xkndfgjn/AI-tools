# -*- coding: utf-8 -*-
"""
ListenThread：常驻监听线程（阶段三框架）。

职责链：等待唤醒 → 录音切段 → STT 转写 → 文本段投递 pipeline（队列一）。
本线程只管「收话 → 转文本 → 投递」，绝不参与对话（ask / TTS 在 DialogThread），
因此监听不会被慢速网络对话阻塞。

三个可替换点（解耦设计，各自独立成方法 / 注入依赖）：
    1. 唤醒检测  → _wait_wakeword()：内部委托注入的 wake（core.wake）。
       后续接 Porcupine：实现 WakeWordDetector.wait_for_wakeword() 即可，
       本线程零改动；替换为任意唤醒引擎（如 Vosk 关键词、自研能量唤醒）
       只要实现同一个 wait_for_wakeword 接口。
    2. VAD 切段  → _capture_utterance()：内部委托注入的 record_func
       （main.record_audio：能量静音检测切段）。可换算法：换一个
       record_audio(duration, sample_rate, blocksize, input_device,
       silence_ratio) -> float32 数组 签名一致的函数注入即可
       （如 WebRTC VAD 切段、活动语音检测专用库）。
    3. STT 转写  → _transcribe()：内部委托注入的 stt（core.stt）。
       可换引擎：任何实现 transcribe(audio) -> str 的对象
       （faster-whisper / 云端 API / 本地流式识别），接口不变。

唤醒态 ↔ 监听态状态机（本轮为简化版）：
      唤醒态 --wait_for_wakeword() 命中--> 监听态（录一段 → 转写 → 投递）
      监听态 --一段处理完--> 回到唤醒态
  连续监听态（唤醒后持续采集、静音超过阈值才回唤醒态）留待后续细化，见 TODO。
"""

import threading
import time


class ListenThread(threading.Thread):
    """常驻监听线程：收话 → 转文本 → 投递队列一。"""

    def __init__(self, pipeline, stt, wake, record_func,
                 listen_timeout: float = 8.0, sample_rate: int = 16000,
                 blocksize: int = 3200, input_device=None,
                 silence_ratio: float = 1.2, wake_retry_delay: float = 1.0,
                 name: str = "listen"):
        """
        依赖全部由构造注入（禁止模块内部 import 全局实例）：
            pipeline / stt / wake / record_func 都是接口，换实现只改 main.py 装配处。

        参数:
            pipeline: Pipeline 实例（core.pipeline），投递用 pipeline.feed_segment。
            stt: SpeechToText 实例（core.stt），transcribe(audio) -> str。
            wake: WakeWordDetector 实例（core.wake），wait_for_wakeword() -> bool。
            record_func: 录音/VAD 切段函数（main.record_audio，参数注入避免循环导入），
                         签名 record_audio(duration, sample_rate, blocksize,
                         input_device, silence_ratio) -> float32 数组。
            listen_timeout: 单段最长录音秒数（config.app.listen_timeout）。
            sample_rate: 采样率（config.stt.sample_rate）。
            blocksize: 音频块大小（config.stt.blocksize）。
            input_device: 录音设备序号（config.stt.input_device）。
            silence_ratio: 静音判定阈值（config.app.silence_ratio）。
            wake_retry_delay: 唤醒检测异常后的重试间隔秒数（config.app.wake_retry_delay）。
            name: 线程名，默认 "listen"。
        """
        super().__init__(name=name, daemon=True)  # daemon：主线程退出不阻塞
        self._pipeline = pipeline
        self._stt = stt
        self._wake = wake
        self._record = record_func
        self._listen_timeout = listen_timeout
        self._sample_rate = sample_rate
        self._blocksize = blocksize
        self._input_device = input_device
        self._silence_ratio = silence_ratio
        self._wake_retry_delay = wake_retry_delay
        self._stop_event = threading.Event()

    def run(self) -> None:
        """线程主循环：唤醒 → 录音切段 → 转写 → 投递，循环往复。

        三个环节各自独立成方法（见类 docstring 的可替换点说明），
        任一环节失败只跳过本轮，不回导致线程退出。

        TODO(连续监听态)：当前一轮只采一段语音就回唤醒态；后续细化状态机
        为「唤醒后进入监听态，常驻采集切段，静音超过阈值（如 5s）才回唤醒态」，
        让用户在对话过程中不用反复说唤醒词。
        """
        print("[listener] 监听线程启动，等待唤醒（当前 wake 为骨架，免唤醒直录）")
        while not self._stop_event.is_set():
            # ---- ① 唤醒检测（可替换：Porcupine / Vosk / 能量唤醒）----
            if not self._wait_wakeword():
                continue
            if self._stop_event.is_set():
                break

            # ---- ② VAD 切段 + 录音（可替换：能量静音 / WebRTC VAD）----
            audio = self._capture_utterance()
            if audio is None or len(audio) == 0:
                print("[listener] 未采到有效音频，回到等待唤醒")
                continue

            # ---- ③ STT 转写（可替换：faster-whisper / 云端 API / 流式识别）----
            text = self._transcribe(audio)
            if not text:
                print("[listener] 未识别到有效内容，回到等待唤醒")
                continue
            print(f"[user] {text}")

            # ---- 投递：只进队列一，不碰对话 ----
            self._pipeline.feed_segment(text)

        print("[listener] 监听线程退出")

    # ------------------------------------------------------------------
    # 三个可替换环节（各自薄封装注入依赖，换实现只动这里或换注入对象）
    # ------------------------------------------------------------------
    def _wait_wakeword(self) -> bool:
        """① 唤醒检测：阻塞等待唤醒词，命中返回 True。

        可替换点：当前委托 wake.wait_for_wakeword()（骨架恒真 = 免唤醒直录）；
        后续接 Porcupine 只需实现该接口，本方法不变。
        异常时告警并短暂重试（间隔 config.app.wake_retry_delay），不退出线程。
        """
        try:
            return bool(self._wake.wait_for_wakeword())
        except Exception as e:
            print(f"[listener] 唤醒检测异常：{e}，{self._wake_retry_delay}s 后重试")
            time.sleep(self._wake_retry_delay)
            return False

    def _capture_utterance(self):
        """② VAD 切段 + 录音：采一段语音，返回 float32 数组（空 = 无效段）。

        可替换点：当前委托 record_func（main.record_audio：能量静音检测切段）；
        换 WebRTC VAD / 其它切段算法时，注入签名一致的函数即可。
        """
        return self._record(
            self._listen_timeout,
            self._sample_rate,
            blocksize=self._blocksize,
            input_device=self._input_device,
            silence_ratio=self._silence_ratio,
        )

    def _transcribe(self, audio) -> str:
        """③ STT 转写：把一段音频转成文本，返回空串 = 无有效内容。

        可替换点：当前委托 stt.transcribe（faster-whisper）；
        换云端 API / 流式识别时，注入任何实现 transcribe(audio) -> str 的对象。
        异常时告警并返回空串（回到唤醒态），不退出线程。
        """
        try:
            return self._stt.transcribe(audio)
        except Exception as e:
            print(f"[listener] 转写失败：{e}")
            return ""

    # ------------------------------------------------------------------
    def stop(self) -> None:
        """请求监听线程停止：置停止标志，并尝试打断阻塞中的唤醒监听。

        线程安全：可在主线程调用。被唤醒模块打断后 wait_for_wakeword
        应尽快返回（抛异常或返回 False），_wait_wakeword 的异常处理会兜底。
        """
        self._stop_event.set()
        try:
            self._wake.stop()
        except Exception as e:
            print(f"[listener] 停止唤醒模块时异常（忽略）：{e}")
