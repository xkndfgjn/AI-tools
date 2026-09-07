# -*- coding: utf-8 -*-
"""
HanaClient：与 Hana server 通信的核心模块（已完成，可直接运行）。

职责：
- HTTP：health / list_sessions / new_session / switch_session
- WebSocket：ask(text) 发一句话，内部完成
  连接 -> 鉴权 -> 发 prompt -> 累积 text_delta -> turn_end/error 判定 -> 返回完整回复，
  带超时保护与可读的中文错误信息。

协议要点（已实测，见 D:\\OH-WorkSpace\\ws-probe.js）：
- 基地址 http://127.0.0.1:{port}，所有请求带请求头 Authorization: Bearer {token}
- WebSocket 地址 ws://127.0.0.1:{port}/ws，连接时同样带鉴权头
- 发送用户消息：{"type": "prompt", "text": "...", "sessionId": "...", "sessionPath": "..."}
- 服务端事件：text_delta(含 delta 增量文本)、turn_end(本轮结束)、error(含 message)、
  status(含 isStreaming)、mood_start/text/end、thinking_start/end、tool_start/end

使用示例：
    from core.config import load_server_info
    from core.hana_client import HanaClient

    info = load_server_info()
    client = HanaClient(info["port"], info["token"], timeout=60)
    print(client.ask("你好"))
"""

import json
import time
import urllib.error
import urllib.request

import websocket  # pip install websocket-client


class HanaClientError(Exception):
    """HanaClient 相关错误，message 为可读的中文信息。"""


class HanaClient:
    """封装 Hana server 的 HTTP 与 WebSocket 通信。"""

    def __init__(self, port: int, token: str, timeout: float = 60.0):
        self.port = port
        self.token = token
        self.timeout = timeout  # 单轮对话整体超时（秒）
        self.base_url = f"http://127.0.0.1:{port}"
        self.ws_url = f"ws://127.0.0.1:{port}/ws"
        self._headers = {"Authorization": f"Bearer {token}"}
        # 会话状态：懒创建，首次 ask 自动 new_session，之后复用（保留上下文）
        self._session_id = None
        self._session_path = None

    # ------------------------------------------------------------------
    # HTTP 基础
    # ------------------------------------------------------------------
    def _http_request(self, method: str, path: str, body: dict = None):
        """通用 HTTP 请求，返回解析后的 JSON（dict 或 list）。失败抛 HanaClientError。"""
        url = self.base_url + path
        headers = dict(self._headers)
        headers["Content-Type"] = "application/json"
        data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            raise HanaClientError(f"HTTP {method} {path} 失败（{e.code}）：{e.reason}")
        except urllib.error.URLError as e:
            raise HanaClientError(f"无法连接 Hana server（{path}）：{e.reason}")

    # ------------------------------------------------------------------
    # HTTP 接口
    # ------------------------------------------------------------------
    def health(self) -> dict:
        """健康检查，返回 {agentId, agent, user, ...}。"""
        return self._http_request("GET", "/api/health")

    def list_sessions(self) -> list:
        """列出所有会话，返回 [{sessionId, path, ...}, ...]。"""
        data = self._http_request("GET", "/api/sessions")
        return data.get("sessions", []) if isinstance(data, dict) else data

    def new_session(self) -> dict:
        """新建会话并设为当前会话，返回 {ok, sessionId, path}。"""
        data = self._http_request("POST", "/api/sessions/new", body={})
        self._session_id = data.get("sessionId") or data.get("id")
        self._session_path = data.get("path") or data.get("sessionPath")
        return data

    def switch_session(self, path: str) -> dict:
        """切换到指定 path 的会话。"""
        return self._http_request("POST", "/api/sessions/switch", body={"path": path})

    def set_thinking_level(self, session_path: str = None, level: str = "medium") -> dict:
        """设置会话的思考强度（thinking level），影响 Hana 回复前的思考量。

        Hana server 已确认支持该接口：POST /api/session-thinking-level。

        参数:
            session_path: 目标会话 path；传 None 时自动创建/复用当前会话
                          （与 ask 用同一会话，保证 level 对本轮对话生效）。
            level: 思考强度，合法值 off / minimal / low / medium / high / xhigh。

        返回:
            服务端响应 dict（通常含 ok 字段）。

        异常:
            HanaClientError: 参数非法 / 网络错误 / 服务端报错。
            调用方应捕获本异常并降级（跳过设置、继续 ask），不要阻断对话。
        """
        _VALID = {"off", "minimal", "low", "medium", "high", "xhigh"}
        if level not in _VALID:
            raise HanaClientError(
                f"非法的 thinking level：{level!r}"
                "（合法值：off/minimal/low/medium/high/xhigh）"
            )
        if session_path is None:
            session_path = self._ensure_session()[1]  # 无会话先建，与 ask 复用同一会话
        return self._http_request(
            "POST",
            "/api/session-thinking-level",
            body={"sessionPath": session_path, "level": level},
        )

    # ------------------------------------------------------------------
    # WebSocket 对话
    # ------------------------------------------------------------------
    def _ensure_session(self):
        """懒创建会话：首次调用时 new_session，之后复用同一会话。"""
        if not self._session_id or not self._session_path:
            self.new_session()
        return self._session_id, self._session_path

    def ask(self, text: str, retries: int = 3, retry_delay: float = 3.0) -> str:
        """发送一句话并等待完整回复，返回拼接后的回复文本。

        Hana server 对话是单工的，连续快速调用可能撞车：一种情况是上一轮
        尚未收尾（还在说话/请等一下），server 返回 error；另一种是 turn_end
        时没有 text_delta，回复为空串。两种情况都视为可重试的异常，关闭当前
        连接、等待 retry_delay 秒后重新走完整流程（重新建连、重发 prompt），
        最多 retries 次（含首次）。

        参数:
            text: 用户说的话（一句）。
            retries: 总尝试次数（含首次），默认 3。
            retry_delay: 每次重试前的等待秒数，默认 3.0。

        返回:
            完整回复文本（text_delta 累积结果）。

        异常:
            HanaClientError: 重试耗尽后仍有 server error / 空回复 / 超时等。
        """
        retries = max(1, int(retries))  # 防御：保证至少尝试一次
        for attempt in range(1, retries + 1):
            try:
                reply = self._ask_once(text)
            except HanaClientError as e:
                # 只对"忙"类 error 重试，其余原样抛出
                busy = "还在说话" in str(e) or "请等一下" in str(e)
                if busy and attempt < retries:
                    print(
                        f"[hana_client] server 忙，{retry_delay}s 后重试（第 {attempt + 1}/{retries} 次）"
                    )
                    time.sleep(retry_delay)
                    continue
                raise
            if reply.strip():
                return reply
            # 空回复视为异常：同样等待后重试，计入 retries 次数，不会无限重试
            if attempt < retries:
                print(
                    f"[hana_client] 收到空回复，{retry_delay}s 后重试（第 {attempt + 1}/{retries} 次）"
                )
                time.sleep(retry_delay)
                continue
            raise HanaClientError("对话正常结束但回复为空，重试后仍为空，请稍后再试")

    def _ask_once(self, text: str) -> str:
        """单次对话尝试：连接 WS（带鉴权头）-> 发 prompt -> 循环收事件 ->
        text_delta 累积、turn_end 结束、error 抛错、超时抛错，返回完整回复。

        server 的"忙"类 error 也在此抛出，由 ask() 统一重试处理。

        返回:
            完整回复文本（text_delta 累积结果）。

        异常:
            HanaClientError: 连接失败 / 发送失败 / 服务端 error / 超时 / 通信异常。
        """
        session_id, session_path = self._ensure_session()
        deadline = time.monotonic() + self.timeout

        # 1. 建立 WebSocket 连接（请求头带鉴权）
        try:
            ws = websocket.create_connection(
                self.ws_url,
                header=[f"Authorization: Bearer {self.token}"],
                timeout=10,  # 连接阶段超时
            )
        except Exception as e:
            raise HanaClientError(f"WebSocket 连接失败：{e}")

        # 2. 发送用户消息
        try:
            payload = {
                "type": "prompt",
                "text": text,
                "sessionId": session_id,
                "sessionPath": session_path,
            }
            ws.send(json.dumps(payload, ensure_ascii=False))
        except Exception as e:
            ws.close()
            raise HanaClientError(f"发送消息失败：{e}")

        # 3. 循环接收事件，累积回复文本
        parts: list[str] = []
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise HanaClientError(
                        f"等待回复超时（{int(self.timeout)}s），请检查 Hana server 是否正常"
                    )
                ws.settimeout(min(remaining, 5))  # 分段等待，便于及时检查整体超时
                try:
                    raw = ws.recv()
                except websocket.WebSocketTimeoutException:
                    continue
                if not raw:
                    continue
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue  # 非 JSON 帧，忽略

                # 与参考实现一致：过滤其他会话的消息
                if msg.get("sessionId") and msg.get("sessionId") != session_id:
                    continue

                mtype = msg.get("type")
                if mtype == "text_delta":
                    parts.append(msg.get("delta") or "")
                elif mtype == "turn_end":
                    break  # 本轮结束，停止接收
                elif mtype == "error":
                    raise HanaClientError(f"对话出错：{msg.get('message') or msg}")
                elif mtype == "status":
                    pass  # 含 isStreaming 状态，当前不需要处理
                # mood_* / thinking_* / tool_* 事件本轮不需要，忽略
        except HanaClientError:
            raise
        except websocket.WebSocketException as e:
            raise HanaClientError(f"WebSocket 通信异常：{e}")
        finally:
            try:
                ws.close()
            except Exception:
                pass

        return "".join(parts)

    def chat_once(self, text: str) -> str:
        """ask 的别名，语义上强调「单轮对话」。"""
        return self.ask(text)
