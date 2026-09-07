# -*- coding: utf-8 -*-
"""
WakeWordDetector：唤醒词检测模块（骨架，阶段四实现）。

接口已定，后续实现者只需实现 wait_for_wakeword：
1. 打开麦克风流（sounddevice 采集 16k 音频）；
2. 逐帧喂给 pvporcupine 的 process()；
3. 命中唤醒词即返回 True。

依赖：pvporcupine、sounddevice（见 requirements.txt）。
注意：pvporcupine 内置的是英文唤醒词；中文「小雅小雅」需要到
Picovoice 控制台（console.picovoice.ai）生成自定义 .ppn 文件，
放到 config 的 wake.keyword_path 后使用。
"""


class WakeWordDetector:
    """阻塞式监听唤醒词。"""

    def __init__(self, keyword_path: str = None, sensitivity: float = 0.5,
                 sample_rate: int = 16000):
        self.keyword_path = keyword_path  # .ppn 文件路径；None 用 porcupine 内置英文词
        self.sensitivity = sensitivity    # 0.0 ~ 1.0，越高越灵敏也越易误触发
        self.sample_rate = sample_rate    # 音频采样率（porcupine 固定 16k）

    def wait_for_wakeword(self) -> bool:
        """阻塞等待唤醒词出现，监听到后返回 True。

        返回:
            True 表示已唤醒，调用方可以开始录音。

        TODO(阶段四)：用 pvporcupine 实现，示意代码：
            import pvporcupine
            import sounddevice as sd
            import numpy as np

            porcupine = pvporcupine.create(
                keyword_paths=[self.keyword_path] if self.keyword_path else None,
                sensitivities=[self.sensitivity],
            )
            with sd.InputStream(samplerate=self.sample_rate, channels=1,
                                dtype="int16", blocksize=porcupine.frame_length) as stream:
                while True:
                    frame = np.frombuffer(stream.read(porcupine.frame_length), dtype="int16")
                    if porcupine.process(frame) >= 0:
                        return True

        当前为占位实现：不监听，直接返回 True（跳过唤醒，便于先行联调主流程）。
        """
        print("[wake] 占位：wait_for_wakeword 尚未实现（阶段四接入 pvporcupine），"
              "跳过唤醒，直接进入录音")
        return True

    def stop(self) -> None:
        """停止监听并释放资源（porcupine 实例、音频流等）。"""
        # TODO(阶段四)：释放 porcupine / 关闭音频流
        pass
