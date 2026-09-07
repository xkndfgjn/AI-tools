# -*- coding: utf-8 -*-
"""
DialogThread：对话线程（阶段三框架）。

职责链：从队列二取 AnalyzedBlock → 按 effort 设置 Hana thinking level →
client.ask(净文本) → 打印回复 → tts.speak 播报。

与监听线程的隔离：
- 对话是慢环节（Hana 思考 + 网络往返 + TTS 合成），本线程独占；
- 监听线程投递只管进队列一，队列二满时由分析层背压（见 pipeline._flush），
  因此对话再慢也不会阻塞麦克风采集。

消费契约：只通过 pipeline.take_block() 取块，不直接操作队列对象；
AnalyzedBlock.metadata 字段由分析层未来扩展使用（相关性分数/置信度等），
对话线程忽略它，因此分析层后续升级不破坏本线程。

降级策略（保证对话不因单点故障中断）：
- set_thinking_level 失败 → 捕获并告警，跳过设置继续 ask（不阻断对话）；
- ask 失败 → 捕获并告警，等下一个块；
- tts.speak 失败 → 捕获并告警，回复文本仍已打印，不丢对话。
"""

import threading


class DialogThread(threading.Thread):
    """对话线程：消费队列二 → 设置 thinking level → ask → TTS 播报。"""

    def __init__(self, pipeline, client, tts, poll_interval: float = 0.5,
                 name: str = "dialog"):
        """
        依赖全部由构造注入（client / tts 可替换，只改 main.py 装配处）：
            client 只要实现 set_thinking_level(session_path, level) 与 ask(text)；
            tts 只要实现 speak(text)。

        参数:
            pipeline: Pipeline 实例（core.pipeline），取块用 pipeline.take_block。
            client: HanaClient 实例（core.hana_client）。
            tts: TextToSpeech 实例（core.tts），speak(reply)（当前为骨架打印占位）。
            poll_interval: 空队列轮询间隔秒数（config.pipeline.poll_interval）。
            name: 线程名，默认 "dialog"。
        """
        super().__init__(name=name, daemon=True)  # daemon：主线程退出不阻塞
        self._pipeline = pipeline
        self._client = client
        self._tts = tts
        self._poll_interval = poll_interval
        self._stop_event = threading.Event()

    def run(self) -> None:
        """线程主循环：等队列二的分析块，逐个对话处理。"""
        print("[dialog] 对话线程启动")
        while not self._stop_event.is_set():
            block = self._pipeline.take_block(timeout=self._poll_interval)
            if block is None:
                continue  # 空队列超时，回到循环头检查停止标志
            self._handle_block(block)
        print("[dialog] 对话线程退出")

    # ------------------------------------------------------------------
    def _handle_block(self, block) -> None:
        """处理一块净文本：设 level → ask → 打印 → TTS。任一环节失败不阻断后续。

        参数:
            block: AnalyzedBlock（net_text / effort_level / segments / metadata）。
                   metadata 由分析层扩展使用，这里忽略，保证扩展不破坏队列二契约。
        """
        print(f"[dialog] 取到分析块：effort={block.effort_level}，"
              f"段数={block.segments}，文本={block.net_text!r}")

        # 1. 按 effort 设置 thinking level（失败降级：不设置，继续对话）
        try:
            self._client.set_thinking_level(session_path=None,
                                            level=block.effort_level)
        except Exception as e:
            print(f"[dialog] 设置 thinking level 失败（降级为默认，继续对话）：{e}")

        # 2. 净文本提交对话
        try:
            reply = self._client.ask(block.net_text)
        except Exception as e:
            print(f"[dialog] 对话失败（本块跳过，等待下一块）：{e}")
            return
        if not reply:
            print("[dialog] 回复为空（本块跳过，等待下一块）")
            return
        print(f"[小雅] {reply}")

        # 3. TTS 播报（当前为骨架，会打印占位日志，正常）
        try:
            self._tts.speak(reply)
        except Exception as e:
            print(f"[dialog] TTS 播报失败（回复已打印，不丢对话）：{e}")

    def stop(self) -> None:
        """请求对话线程停止：置停止标志，get 超时后自动退出。

        线程安全：可在主线程调用。正在进行的 ask / tts.speak 不会被打断，
        会自然完成后由 join 等待（超时则交给 daemon 机制兜底）。
        """
        self._stop_event.set()
