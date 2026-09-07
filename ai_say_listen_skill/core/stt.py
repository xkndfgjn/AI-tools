# -*- coding: utf-8 -*-
"""
SpeechToText：语音转文字模块（阶段一完成）。

职责：
- 用 faster-whisper 加载 Whisper 模型，把 16k 采样率的 float32 音频转成中文文本。
- 模型懒加载：首次 transcribe 时才加载，避免程序启动慢（small 模型约 461MB）。

依赖：faster-whisper（见 requirements.txt）。
模型：首次转写时 faster-whisper 自动从 HuggingFace 下载到本地缓存，无需手动下载；
网络受限时可设环境变量 HF_ENDPOINT=https://hf-mirror.com 后重试。
"""

import numpy as np


class STTError(Exception):
    """SpeechToText 相关错误，message 为可读的中文信息。"""


class SpeechToText:
    """把一段 16k float32 PCM 音频转成文字。"""

    def __init__(self, model: str = "small", device: str = "auto",
                 language: str = "zh", sample_rate: int = 16000):
        self.model = model        # faster-whisper 模型档位：base / small / medium / large-v3
        self.device = device      # auto / cpu / cuda
        self.language = language  # 转写语言，"zh" 或 None（自动检测）
        self.sample_rate = sample_rate  # 期望的音频采样率（16k）
        self._model = None        # 懒加载缓存：首次 transcribe 时填充

    def _load_model(self):
        """加载并缓存 Whisper 模型，只执行一次。

        说明：
        - compute_type="int8"：内存/显存占用小，CPU 上速度快，中文识别够用；
          若机器有 NVIDIA GPU 且想追求更高精度，可改 "float16"（或 "float32"）。
        - 首次构造会自动从 HuggingFace 下载模型；下载失败抛出带镜像提示的中文异常。
        """
        if self._model is not None:
            return self._model

        try:
            from faster_whisper import WhisperModel
        except ImportError:
            raise STTError(
                "未安装 faster-whisper，请先执行：python scripts/setup_env.py"
            )

        try:
            self._model = WhisperModel(
                self.model, device=self.device, compute_type="int8"
            )
        except Exception as e:
            raise STTError(
                f"加载 Whisper 模型失败（model={self.model}）：{e}\n"
                "模型首次使用需从 HuggingFace 下载，网络受限时可设置镜像后重试：\n"
                "  set HF_ENDPOINT=https://hf-mirror.com"
            ) from e
        return self._model

    def transcribe(self, audio) -> str:
        """把音频转成文字，返回识别文本；无有效语音时返回空串 ""。

        参数:
            audio: float32 的 numpy 数组（或可转为 float32 的序列），
                   采样率为 self.sample_rate，由录音模块（main.record_audio）产出。

        返回:
            识别出的文字（首尾空白已去除）；音频为空时返回空串。

        异常:
            STTError: 模型加载失败或转写失败，message 为中文信息。
        """
        if audio is None or len(audio) == 0:
            return ""
        audio = np.asarray(audio, dtype=np.float32)
        if audio.size == 0:
            return ""

        model = self._load_model()
        try:
            # beam_size=5：比贪心解码（1）精度更高，中文长句表现更好；
            # vad_filter=True：自动跳过静音段，减少无效转写、加快速度。
            segments, _ = model.transcribe(
                audio,
                language=self.language or None,  # None 表示自动检测语言
                beam_size=5,
                vad_filter=True,
            )
            return "".join(seg.text for seg in segments).strip()
        except STTError:
            raise
        except Exception as e:
            raise STTError(f"语音转写失败：{e}") from e

    def __call__(self, audio) -> str:
        """便于 main.py 直接以 stt(audio) 形式调用。"""
        return self.transcribe(audio)
