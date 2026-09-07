# -*- coding: utf-8 -*-
"""
Analyzer：分析层（阶段三框架核心）。

职责（从队列一消费的文本段 → 净文本块）：
    1. 分组（_group_segments）：相关段落合并成块。
    2. 改口检测（_detect_revision）：用户改口则作废前文，只保留其后内容。
    3. 强度打分（_score_effort）：按净文本信息密度估算思考强度 effort 等级。

实现模式（config.analyzer.analyzer_mode，默认 "rules"）：
- "rules"：规则版（词表 + 长度分档），即本轮实现。
- "semantic"：语义版（embedding / LLM），与规则版共用同一接口
  analyze(segments, last_ts) -> AnalyzedBlock | None，只是换实现。
  本轮未实现：mode 设为 "semantic" 时调用会抛 NotImplementedError。
  后续实现语义版时，只需把 _analyze_semantic 的 TODO 填上，
  pipeline / 监听线程 / 对话线程零改动（接口与数据契约不变）。

可插拔契约（对 pipeline 稳定，算法实现与接口分离）：
    analyze(segments: list[str], last_ts: float) -> AnalyzedBlock | None
    三个职责各自是独立方法；换算法版本只改 analyzer_mode 或换实现内部逻辑。

effort 合法值：off / minimal / low / medium / high / xhigh（Hana server 已确认支持）。

解耦说明：本模块不内置任何默认词表或阈值。词表、长度分档上界（effort_bounds）、
chitchat_max_len、default_effort 全部由构造参数从 config.analyzer 段传入
（唯一兜底源是 core/config.py 的 DEFAULTS），代码里无写死的词表/魔法数字。
"""

from typing import List, Optional

from core.pipeline import AnalyzedBlock


class Analyzer:
    """把一组文本段分析成一块净文本（AnalyzedBlock）。

    接口契约（对 pipeline 稳定）：
        analyze(segments: list[str], last_ts: float) -> AnalyzedBlock | None
    算法版本通过 analyzer_mode 在 analyze() 内分派（见 _analyze_rules / _analyze_semantic）。
    """

    # 协议常量（不属于可调配置，是 Hana server 端契约）：
    # effort 合法值偏序，hana_client.set_thinking_level 的校验集与之同源
    EFFORT_LEVELS = ("off", "minimal", "low", "medium", "high", "xhigh")
    # analyzer_mode 合法值
    VALID_MODES = ("rules", "semantic")
    # effort_bounds 必需键（长度分档上界，字符数；值从 config.analyzer.effort_bounds 读）
    _BOUND_KEYS = ("minimal", "low", "medium", "high")

    def __init__(self, analyzer_mode: str, revision_words: List[str],
                 chitchat_words: List[str], danger_words: List[str],
                 complex_words: List[str], default_effort: str,
                 effort_bounds: dict, chitchat_max_len: int):
        """所有参数必须显式传入（来自 config.analyzer 段），代码里不设默认值。

        config 是词表/阈值的唯一兜底源：config.json 缺失字段时，
        core/config.py 的 DEFAULTS 会补齐，main.py 装配时读到的一定是完整段。

        参数:
            analyzer_mode: "rules"（规则版）| "semantic"（语义版，未实现）。
            revision_words: 改口词表（命中后该词及之前文本作废）。
            chitchat_words: 闲聊词表（寒暄 → off/low）。
            danger_words: 危险操作词表（删/发/付/提交 → xhigh）。
            complex_words: 复杂任务词表（分析/对比/方案 → high）。
            default_effort: 无信号词时中段文本（low~medium 上界之间）的默认档。
            effort_bounds: 长度分档上界 {"minimal":4, "low":16, "medium":60, "high":200}，
                           ≤ minimal → minimal，…，> high → xhigh。
            chitchat_max_len: 命中闲聊词且整句 ≤ 该长度 → off（纯寒暄），否则 low。

        异常:
            ValueError: 参数缺省 / 非法（强制从 config 传入，杜绝代码内兜底词表）。
        """
        if analyzer_mode not in self.VALID_MODES:
            raise ValueError(
                f"非法的 analyzer_mode：{analyzer_mode!r}（合法值：{list(self.VALID_MODES)}）")

        self.analyzer_mode = analyzer_mode
        self.revision_words = self._require_words("revision_words", revision_words)
        self.chitchat_words = self._require_words("chitchat_words", chitchat_words)
        self.danger_words = self._require_words("danger_words", danger_words)
        self.complex_words = self._require_words("complex_words", complex_words)

        if default_effort not in self.EFFORT_LEVELS:
            raise ValueError(
                f"非法的 default_effort：{default_effort!r}"
                f"（合法值：{list(self.EFFORT_LEVELS)}）")
        self.default_effort = default_effort

        self.effort_bounds = self._require_effort_bounds(effort_bounds)
        self.chitchat_max_len = int(chitchat_max_len)
        if self.chitchat_max_len < 0:
            raise ValueError(f"非法的 chitchat_max_len：{chitchat_max_len!r}（需 ≥ 0）")

    # ------------------------------------------------------------------
    # 构造校验（保证词表/阈值只来自 config）
    # ------------------------------------------------------------------
    @staticmethod
    def _require_words(name: str, words) -> List[str]:
        """校验词表参数：非空、元素为非空字符串；否则报错（不静默兜底）。"""
        if (not isinstance(words, (list, tuple))
                or not words
                or not all(isinstance(w, str) and w.strip() for w in words)):
            raise ValueError(f"{name} 必须是从 config.analyzer 传入的非空词表，"
                             f"实际收到：{words!r}")
        return [w.strip() for w in words]

    @classmethod
    def _require_effort_bounds(cls, effort_bounds: dict) -> dict:
        """校验长度分档上界：必需键齐全、整数、严格递增、非负。"""
        missing = [k for k in cls._BOUND_KEYS if k not in (effort_bounds or {})]
        if missing:
            raise ValueError(
                f"effort_bounds 缺少键 {missing}（需从 config.analyzer.effort_bounds 传入，"
                f"形如 {dict.fromkeys(cls._BOUND_KEYS, 0)}）")
        try:
            bounds = {k: int(effort_bounds[k]) for k in cls._BOUND_KEYS}
        except (TypeError, ValueError):
            raise ValueError(f"effort_bounds 各值需为整数，实际收到：{effort_bounds!r}")
        values = list(bounds.values())
        if values != sorted(values) or values[0] < 0:
            raise ValueError(f"effort_bounds 必须是递增的非负上界，实际收到：{bounds}")
        return bounds

    # ------------------------------------------------------------------
    # 对外入口（稳定接口 + 模式分派点）
    # ------------------------------------------------------------------
    def analyze(self, segments: List[str], last_ts: float) -> Optional[AnalyzedBlock]:
        """分析一组文本段，返回净文本块；块不成立（如整块被改口作废）返回 None。

        【模式分派点】analyzer_mode 决定用哪套实现，接口不变：
            - "rules"    → _analyze_rules（本轮：词表 + 长度）
            - "semantic" → _analyze_semantic（TODO：embedding/LLM，同一接口换实现）
        后续新增算法版本只需在此加分支（或换用策略注册表），调用方零改动。

        参数:
            segments: 来自队列一、已由 pipeline 按 burst_window 聚成一块的文本段列表。
            last_ts: 块内最后一段的时间戳（time.monotonic）。
                    本轮暂不使用，预留给语义级分组（如跨块合并时判断时间间隔）。

        返回:
            AnalyzedBlock(net_text, effort_level, segments, metadata)，或 None（块不成立）。
        """
        if self.analyzer_mode == "semantic":
            return self._analyze_semantic(segments, last_ts)
        return self._analyze_rules(segments, last_ts)

    # ------------------------------------------------------------------
    # 语义版（TODO：同一接口换实现）
    # ------------------------------------------------------------------
    def _analyze_semantic(self, segments: List[str], last_ts: float) -> Optional[AnalyzedBlock]:
        """语义版分析入口（TODO，本轮未实现）。

        与规则版返回相同契约（AnalyzedBlock，metadata 可塞相关性分数/置信度）。
        实现方向（见各职责方法内 TODO）：
            - 分组：embedding / LLM 段间连贯性评分（参考「话语对连贯性评分」思路）；
            - 改口：意图反转 / 否定焦点识别；
            - 打分：意图类型 + 句法复杂度加权。
        """
        raise NotImplementedError(
            "analyzer_mode='semantic' 尚未实现。请将 config.analyzer.analyzer_mode "
            "改为 'rules'，或按 TODO 实现 _analyze_semantic（接口不变，pipeline 零改动）")

    # ------------------------------------------------------------------
    # 规则版实现（本轮）
    # ------------------------------------------------------------------
    def _analyze_rules(self, segments: List[str], last_ts: float) -> Optional[AnalyzedBlock]:
        """规则版分析：分组（合并）→ 改口（词表）→ 打分（长度 + 信号词）。"""
        # 过滤空段（防御：pipeline 已过滤，这里再兜底一次）
        segments = [s.strip() for s in segments if s and s.strip()]
        if not segments:
            return None

        # a) 分组：本轮简化 = 全部合并进一块（时间合并由 pipeline 控制）
        merged = self._group_segments(segments)
        if not merged.strip():
            return None

        # b) 改口检测：返回净文本
        net_text = self._detect_revision(segments)
        if not net_text.strip():
            return None  # 整块被改口作废，块不成立

        # c) 强度打分
        effort = self._score_effort(net_text)
        return AnalyzedBlock(
            net_text=net_text,
            effort_level=effort,
            segments=len(segments),
            metadata={"analyzer_mode": self.analyzer_mode},  # 语义版可在此塞更多信息
        )

    # ------------------------------------------------------------------
    # 三职责接口
    # ------------------------------------------------------------------
    def _group_segments(self, segments: List[str]) -> str:
        """① 分组：把相关段落合并成块文本。

        本轮简化实现：全部段拼接为一段文本（用空格分隔，避免跨段粘连产生
        伪改口词）。时间维度的合并已由 pipeline 的 burst_window 完成。

        TODO(语义级分组)：对段间做语义连贯性评分（embedding 余弦 / LLM 判断
        是否同一个话题），语义相关的段才并入一块；不相关的段拆成多个块输出。
        参考「话语对连贯性评分」思路：相邻段的话题重合度、指代衔接
        （这/那/它 的先行词）、因果承接关系。
        """
        return " ".join(segments)

    def _detect_revision(self, segments: List[str]) -> str:
        """② 改口检测：命中改口词后，该词及之前文本作废，只保留其后内容。

        本轮简化实现（词表版，词表来自 config.analyzer.revision_words）：
            把各段用空格拼成一句，扫描改口词表中每个词的最后一次出现位置，
            以最后命中处的词尾为界，其后文本即净文本；无命中则整句保留。

        已知局限（留给语义级改口解决）：
            - "算了" 单独成段时，净文本会残留其后内容（如"不用了"），
              本应整段作废；
            - 不含词表词的改口（如"哦不对，我改主意了"前半句用词不同）无法识别。

        TODO(语义级改口)：结合意图反转、否定焦点识别改口；对"作废类"表达
        （算了/不用了/没事了）整块丢弃。
        """
        joined = " ".join(segments)

        # 找所有改口词的最后一个出现位置（rfind 逐词比较）
        last_pos = -1
        last_word_len = 0
        for word in self.revision_words:
            pos = joined.rfind(word)
            if pos > last_pos:
                last_pos = pos
                last_word_len = len(word)

        if last_pos < 0:
            return joined  # 无改口，全部保留

        # 取改口词之后的内容，并去掉拼接残留的空格与标点
        # （注意：strip 指定 chars 时不会自动去空白，需把空白显式放进字符集）
        net = joined[last_pos + last_word_len:]
        return net.strip(" \t\n\r，。！？,.!?;；:：")

    def _score_effort(self, net_text: str) -> str:
        """③ 强度打分：估算思考强度 effort 等级，返回合法等级字符串。

        本轮简化实现（长度 + 信号词；分档阈值来自 config.analyzer.effort_bounds）：
            1. 危险词命中（删除/发送/支付/提交…）→ xhigh（涉及操作，保守求稳）；
            2. 复杂词命中（分析/对比/方案/总结/解释…）→ 至少 high；
            3. 闲聊词命中（你好/谢谢/晚安/再见…）：
               - 整句 ≤ config.analyzer.chitchat_max_len → off（纯寒暄）；
               - 否则 → low（可能夹杂任务，但主体是闲聊）；
            4. 无信号词 → 按长度分档（effort_bounds）：
               ≤ minimal → minimal，≤ low → low，≤ medium → default_effort，
               ≤ high → high，超过 → xhigh。

        TODO(精细打分)：结合意图类型（问事实/要操作/要创作）、句法复杂度、
        否定与条件结构、专有名词密度等，用模型或加权规则替代长度+词表。
        """
        n = len(net_text)
        b = self.effort_bounds

        danger_hit = any(w in net_text for w in self.danger_words)
        complex_hit = any(w in net_text for w in self.complex_words)
        chitchat_hit = any(w in net_text for w in self.chitchat_words)

        if danger_hit:
            return "xhigh"

        if complex_hit:
            # 复杂任务至少 high；特别长的复杂任务可以更高
            return "xhigh" if n > b["high"] else "high"

        if chitchat_hit:
            return "off" if n <= self.chitchat_max_len else "low"

        # 无信号词：按长度分档
        if n <= b["minimal"]:
            return "minimal"
        if n <= b["low"]:
            return "low"
        if n <= b["medium"]:
            return self.default_effort
        if n <= b["high"]:
            return "high"
        return "xhigh"
