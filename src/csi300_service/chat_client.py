"""Streaming chat transport, independent of Tk and strategy generation."""
from __future__ import annotations

from dataclasses import dataclass
import json
import threading
from typing import Any, Callable
from urllib.request import Request

from .ai_strategy import OpenAICompatibleJSONClient


class ChatCancelled(Exception):
    pass


class ChatProtocolError(RuntimeError):
    pass


class ChatCancellation:
    def __init__(self):
        self.event = threading.Event()
        self.lock = threading.Lock()
        self.response: Any = None

    def attach(self, response: Any) -> None:
        with self.lock:
            self.response = response
        if self.event.is_set():
            response.close()
            raise ChatCancelled()

    def cancel(self) -> None:
        self.event.set()
        with self.lock:
            response = self.response
        if response is not None:
            # Buffered HTTP reads may hold an internal lock. Never wait on it in Tk.
            def close() -> None:
                try:
                    response.close()
                except Exception:
                    pass
            threading.Thread(target=close, daemon=True).start()


@dataclass
class ChatResult:
    text: str
    finish_reason: str = "stop"
    usage: dict | None = None


class StreamingChatClient(OpenAICompatibleJSONClient):
    def list_models(self) -> list[str]:
        request = Request(f"{self.base_url}/models", headers={"Authorization": f"Bearer {self.api_key}"})
        try:
            with self.opener(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
            return sorted({item["id"] for item in payload["data"] if isinstance(item.get("id"), str)})
        except Exception as exc:
            raise RuntimeError(self._error_message(exc)) from exc

    def stream_chat(
        self, system_prompt: str, messages: list[dict[str, str]], *,
        on_token: Callable[[str], None], cancellation: ChatCancellation,
        temperature: float = 0.7, max_tokens: int = 4096,
        on_thinking: Callable[[], None] | None = None,
    ) -> ChatResult:
        if not self.api_key:
            raise ValueError("请先在模型设置中填写 API Key")
        if cancellation.event.is_set():
            raise ChatCancelled()
        payload = {
            "model": self.model, "stream": True,
            "messages": [{"role": "system", "content": system_prompt}, *messages],
            "temperature": temperature, "max_tokens": max_tokens,
        }
        request = Request(f"{self.base_url}/chat/completions", data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                          headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json", "Accept": "text/event-stream"}, method="POST")
        response = None
        parts: list[str] = []
        reason, usage, finished, thinking = "stop", None, False, False
        try:
            response = self.opener(request, timeout=45)
            cancellation.attach(response)

            def consume(data: str) -> bool:
                nonlocal reason, usage, finished, thinking
                if data.strip() == "[DONE]":
                    finished = True
                    return True
                event = json.loads(data)
                if event.get("error"):
                    raise ValueError("服务在流中返回错误")
                if isinstance(event.get("usage"), dict):
                    usage = event["usage"]
                choices = event.get("choices", [])
                if not choices:
                    return False
                choice = choices[0]
                delta = choice.get("delta") or choice.get("message") or {}
                if delta.get("reasoning_content") and not thinking:
                    thinking = True
                    if on_thinking:
                        on_thinking()
                content = delta.get("content")
                if isinstance(content, str) and content:
                    parts.append(content)
                    on_token(content)
                if choice.get("finish_reason"):
                    reason = str(choice["finish_reason"])
                    finished = True
                return False

            data_lines: list[str] = []
            while True:
                if cancellation.event.is_set():
                    raise ChatCancelled()
                line = response.readline()
                if not line:
                    if data_lines:
                        consume("\n".join(data_lines))
                    break
                text = line.decode("utf-8").rstrip("\r\n")
                # Some compatible servers ignore stream=True and send a JSON body.
                if not data_lines and text.lstrip().startswith("{"):
                    consume(text + response.read().decode("utf-8"))
                    finished = True
                    break
                if text.startswith("data:"):
                    data_lines.append(text[5:].lstrip(" "))
                elif not text and data_lines:
                    done = consume("\n".join(data_lines))
                    data_lines.clear()
                    if done:
                        break
            if cancellation.event.is_set():
                raise ChatCancelled()
            if not finished:
                raise ChatProtocolError("连接提前中断，已保留部分回复；可以重新生成")
            if not parts or not "".join(parts).strip():
                raise ChatProtocolError("模型没有返回正文，请检查模型设置或提高回复长度")
            return ChatResult("".join(parts), reason, usage)
        except ChatCancelled:
            raise
        except ChatProtocolError:
            if cancellation.event.is_set():
                raise ChatCancelled() from None
            raise
        except Exception as exc:
            if cancellation.event.is_set():
                raise ChatCancelled() from None
            raise RuntimeError(self._error_message(exc)) from exc
        finally:
            if response is not None:
                try:
                    response.close()
                except Exception:
                    pass
