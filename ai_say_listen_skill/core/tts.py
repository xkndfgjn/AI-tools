# -*- coding: utf-8 -*-
"""
TextToSpeech：文字转语音模块（骨架，阶段三实现）。

接口已定，后续实现者只需实现 speak：
1. 用 edge-tts 把文本合成 mp3（字节流）；
2. 用 sounddevice 播放（或调用系统播放器）。

依赖：edge-tts、sounddevice（见 requirements.txt）。
注意：edge-tts 是微软在线合成接口，需要联网；离线环境需换本地 TTS。
"""


class TextToSpeech:
    """把文本合成语音并播放。"""

    def __init__(self, voice: str = "zh-CN-XiaoxiaoNeural",
                 rate: str = "+0%", volume: str = "+0%", output_device=None):
        self.voice = voice          # edge-tts 音色，中文常用 zh-CN-XiaoxiaoNeural
        self.rate = rate            # 语速，如 "+10%" / "-10%"
        self.volume = volume        # 音量，如 "+50%"
        self.output_device = output_device  # sounddevice 播放设备序号，None 用默认

    def speak(self, text: str) -> None:
        """合成并播放一段文本（阻塞至播放结束）。

        参数:
            text: 要朗读的文本（一般是 AI 的回复）。

        TODO(阶段三)：用 edge-tts + sounddevice 实现，示意代码：
            import asyncio
            import edge_tts
            import sounddevice as sd
            import numpy as np

            async def _synth(text):
                communicate = edge_tts.Communicate(text, self.voice, rate=self.rate, volume=self.volume)
                chunks = b""
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        chunks += chunk["data"]
                return chunks

            mp3_bytes = asyncio.run(_synth(text))
            # 将 mp3 解码为 PCM 后用 sounddevice 播放（需要 pydub/audioop 等解码）

        当前为占位实现，打印日志，不阻塞（方便联调）。
        """
        print(f"[tts] 占位：speak 尚未实现（阶段三接入 edge-tts），"
              f"待朗读文本长度 {len(text)}")
