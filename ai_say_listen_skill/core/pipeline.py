# -*- coding: utf-8 -*-
"""
Pipeline：两级队列与净文本提交（阶段三框架核心）。

架构位置（监听线程 / 分析层 / 对话线程之间的数据通道）：

    监听线程 ──feed_segment(text)──▶ 队列一（QueueOne）  收集队列
                                            │
                                            ▼
                                    run_analyzer() 消费线程（分析层）
                                    攒话（burst_window 合并）→ Analyzer.analyze()
                                            │
                                            ▼
                              AnalyzedBlock ──▶ 队列二（QueueTwo）
                                            │
                                            ▼
                                    对话线程（DialogThread 取块对话）

队列数据契约（线程间通信的唯一通道，双方都必须遵守）：
- 队列一（queue_one）：元素为 (text: str, ts: float)。
    text：一段语音的转写文本（已 strip、非空）；
    ts：该段说话结束时刻（time.monotonic 秒），分析层用它判断与上一段的
        间隔是否落在 burst_window 内（攒话合并）。
    生产者：仅监听线程（调用 feed_segment）；消费者：仅分析层线程（run_analyzer）。
- 队列二（queue_two）：元素为 AnalyzedBlock（净文本块，字段契约见下方 dataclass）。
    生产者：仅分析层线程（_flush 封口后投递）；消费者：仅对话线程（take_block）。

线程调用约定：
- 线程之间不互相调用对方内部方法，不共享可变状态；对 pipeline 只允许三个公开入口：
    feed_segment(text)    —— 生产者侧（监听线程）
    take_block(timeout)   —— 消费者侧（对话线程）
    stop()                —— 停止信号（主线程）
- 队列一/队列二对象本身也是公开属性，仅供调试/测试观察，业务线程请走上述入口。

停止协议：主线程先停监听线程（不再 feed）→ pipeline.stop() 投 None 哨兵 →
run_analyzer 排空剩余段与未封口块后退出 → 对话线程由自身 stop_event 退出。
"""

import queue
import threading
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class AnalyzedBlock:
    """分析层产出的一块「净文本」，进队列二，由对话线程消费。

    字段（队列二契约，后续扩展只增不改既有字段）：
        net_text: 净文本（已做分组合并 + 改口作废后的最终提交文本）。
        effort_level: 思考强度等级，合法值 off / minimal / low / medium / high / xhigh。
        segments: 组成这一块的原始文本段数量（便于调试与统计）。
        metadata: 附加信息 dict，可空。供未来语义分析器塞额外数据
                  （如相关性分数、置信度、意图标签），当前规则版放入
                  {"analyzer_mode": ...}；对话线程忽略该字段，
                  因此未来扩展不会破坏队列二契约。
    """
    net_text: str
    effort_level: str
    segments: int
    metadata: Optional[dict] = field(default_factory=dict)


class Pipeline:
    """两级队列与净文本提交。

    用法（依赖全部由构造注入，见 main.py 装配处）：
        pipeline = Pipeline(analyzer, burst_window=..., queue_one_max=...,
                            queue_two_max=..., poll_interval=..., put_timeout=...)
        # 监听线程侧：pipeline.feed_segment(text)
        # 分析层线程侧：threading.Thread(target=pipeline.run_analyzer, daemon=True).start()
        # 对话线程侧：pipeline.take_block(timeout=...)  返回 AnalyzedBlock 或 None
    """

    def __init__(self, analyzer, burst_window: float = 2.5,
                 queue_one_max: int = 50, queue_two_max: int = 20,
                 poll_interval: float = 0.5, put_timeout: float = 1.0):
        """
        参数:
            analyzer: Analyzer 实例（core.analyzer），analyze(segments, last_ts)
                      -> AnalyzedBlock | None。可插拔：换成任何实现同一接口的分析器即可。
            burst_window: 攒话合并窗口（秒，从 config.pipeline.burst_window 读）。
                          新段距块内最后一段的间隔 ≤ 该值则并入当前块，
                          否则封口当前块、以新段另起一块。
            queue_one_max: 队列一容量。满时丢新段并告警（宁可丢语音不阻塞麦克风）。
            queue_two_max: 队列二容量。满时分析层阻塞等待（对话是慢环节，背压优于丢请求）。
            poll_interval: 分析层空闲轮询间隔（秒，从 config.pipeline.poll_interval 读）。
            put_timeout: 队列二满时背压等待的单次超时（秒，从 config.pipeline.put_timeout 读）。
        """
        self.analyzer = analyzer
        self.burst_window = max(0.0, float(burst_window))
        self._poll_interval = max(0.05, float(poll_interval))
        self._put_timeout = max(0.1, float(put_timeout))

        # 队列一：收集队列。元素为 (text, ts)，契约见模块 docstring
        self.queue_one: "queue.Queue[Tuple[str, float]]" = queue.Queue(maxsize=max(1, queue_one_max))
        # 队列二：净文本队列。元素为 AnalyzedBlock，契约见模块 docstring
        self.queue_two: "queue.Queue[AnalyzedBlock]" = queue.Queue(maxsize=max(1, queue_two_max))

        # 以下状态只允许分析层线程（run_analyzer 所在线程）读写
        self._pending: List[Tuple[str, float]] = []   # 攒话中的段列表：(text, ts)
        self._stop = threading.Event()                # 停止信号，线程安全

    # ------------------------------------------------------------------
    # 生产者入口（监听线程）
    # ------------------------------------------------------------------
    def feed_segment(self, text: str, ts: float = None) -> bool:
        """监听线程投递一个文本段进队列一。

        参数:
            text: 一段语音的转写文本（已 strip，非空由调用方保证）。
            ts: 该段说话结束时刻（time.monotonic 秒），默认取投递时刻。

        返回:
            True 投递成功；False 队列满被丢弃（已打印告警）。

        线程安全：本方法只 put 队列，可从任何线程调用。
        """
        if not text or not text.strip():
            return False
        payload = (text.strip(), ts if ts is not None else time.monotonic())
        try:
            self.queue_one.put_nowait(payload)
            return True
        except queue.Full:
            print("[pipeline] 队列一已满，丢弃一个语音段（监听过快或分析层卡住），"
                  f"请检查：{text!r}")
            return False

    # ------------------------------------------------------------------
    # 消费者入口（对话线程）
    # ------------------------------------------------------------------
    def take_block(self, timeout: float = 0.5) -> Optional[AnalyzedBlock]:
        """对话线程从队列二取一个分析块；超时返回 None。

        这是队列二的唯一消费入口：对话线程不直接操作 queue 对象，
        队列实现细节（queue.Queue / 元素类型）对消费者隐藏。

        参数:
            timeout: 空队列等待秒数（调用方传入轮询间隔）。

        返回:
            AnalyzedBlock 或 None（超时无块）。
        """
        try:
            return self.queue_two.get(timeout=timeout)
        except queue.Empty:
            return None

    # ------------------------------------------------------------------
    # 分析层线程入口
    # ------------------------------------------------------------------
    def run_analyzer(self) -> None:
        """分析层线程主循环：消费队列一 → 攒话合并 → 封口后交给 Analyzer → 进队列二。

        攒话合并规则（简化版）：
            新段距块内最后一段间隔 ≤ burst_window → 并入当前块；
            否则封口当前块，新段另起一块。队列空闲时若当前块的最后一段
            距今已超过 burst_window，也会封口（保证单段块不会无限等待）。

        停止方式：外部调 stop() 会投递一个 None 哨兵；本循环消费到哨兵即退出，
        且退出前会把队列一中剩余段与未封口的块处理完，不丢数据。
        """
        print("[pipeline] 分析层线程启动")
        while not self._stop.is_set():
            try:
                item = self.queue_one.get(timeout=self._poll_interval)
            except queue.Empty:
                self._flush_if_stale()  # 队列空闲：检查是否有悬着的尾块该封口
                continue
            if item is None:            # 哨兵：外部调 stop() 投递
                break
            self._accumulate(item)

        # 收尾：清空队列一剩余段并封口（stop 与哨兵竞态时的兜底，保证退出前不丢）
        while True:
            try:
                item = self.queue_one.get_nowait()
            except queue.Empty:
                break
            if item is not None:
                self._accumulate(item)
        self._flush()
        print("[pipeline] 分析层线程退出")

    def stop(self) -> None:
        """请求分析层停止：置停止标志并投递 None 哨兵（run_analyzer 排空后退出）。

        线程安全：可在主线程调用；需在监听线程已停止（不再 feed）之后再调，
        否则哨兵会被后续正常段"插队"，无法保证退出前排空。
        """
        self._stop.set()
        try:
            self.queue_one.put_nowait(None)
        except queue.Full:
            pass  # 队列满时哨兵放不进去：分析层会因 stop 标志在下一次轮询退出

    # ------------------------------------------------------------------
    # 攒话合并（仅分析层线程调用，其它线程不得访问以下私有状态）
    # ------------------------------------------------------------------
    def _accumulate(self, item: Tuple[str, float]) -> None:
        """把新段并入当前块，或封口旧块后另起一块。"""
        text, ts = item
        if self._pending and (ts - self._pending[-1][1]) <= self.burst_window:
            # 距上一段足够近：并入当前块
            self._pending.append((text, ts))
            return
        # 间隔超过窗口（或是首段）：先封口旧块，再以本段开启新块
        if self._pending:
            self._flush()
        self._pending = [(text, ts)]

    def _flush_if_stale(self) -> None:
        """队列空闲时调用：尾块的最后一段距今超过 burst_window 则封口。"""
        if not self._pending:
            return
        if (time.monotonic() - self._pending[-1][1]) > self.burst_window:
            self._flush()

    def _flush(self) -> None:
        """封口当前块：交给 Analyzer 分析，把 AnalyzedBlock 放进队列二。"""
        if not self._pending:
            return
        segments = [text for text, _ in self._pending]
        last_ts = self._pending[-1][1]
        self._pending = []  # 先清空，analyze 卡住也不影响后续攒话

        try:
            block = self.analyzer.analyze(segments, last_ts)
        except Exception as e:
            print(f"[pipeline] 分析层异常（跳过本块）：{e}")
            return
        if block is None:
            print("[pipeline] 块封口：analyzer 判定不成立（如整块被改口作废），丢弃")
            return
        print(f"[pipeline] 块封口：{block.segments} 段 → effort={block.effort_level}")

        # 队列二满时阻塞等空位（对话是慢环节，背压优于丢请求）；期间响应停止信号
        while not self._stop.is_set():
            try:
                self.queue_two.put(block, timeout=self._put_timeout)
                return
            except queue.Full:
                continue
        print("[pipeline] 已收到停止信号或队列二已满，丢弃分析块（退出中）")
