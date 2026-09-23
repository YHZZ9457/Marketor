"""Local chat persistence. Credentials are deliberately excluded from this format."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
import json
import os
from pathlib import Path
import tempfile
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from .catalog import user_storage_dir


def now() -> str:
    return datetime.now().isoformat(timespec="microseconds")


@dataclass
class ChatSettings:
    provider: str = "DeepSeek"
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-v4-flash"
    temperature: float = 0.7
    max_tokens: int = 4096
    context_chars: int = 60000
    system_prompt: str = ""

    @property
    def key_env(self) -> str:
        return "DEEPSEEK_API_KEY" if self.provider == "DeepSeek" else "MARKETOR_AI_API_KEY"

    def validate(self) -> None:
        self.base_url = self.base_url.strip().rstrip("/")
        self.model = self.model.strip()
        url = urlsplit(self.base_url)
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError("Base URL 须为 http(s) 服务地址，不能包含密钥、查询参数或片段")
        if not self.model:
            raise ValueError("请填写模型名称，或获取服务提供的模型列表")
        if self.provider not in {"DeepSeek", "OpenAI 兼容接口"}:
            raise ValueError("未知服务类型")
        if not 0 <= self.temperature <= 2:
            raise ValueError("创造性参数应在 0–2 之间")
        if not 256 <= self.max_tokens <= 32768:
            raise ValueError("回复长度应在 256–32768 tokens 之间")
        if not 4000 <= self.context_chars <= 200000:
            raise ValueError("上下文预算应在 4,000–200,000 字符之间")
        if len(self.system_prompt) > 8000:
            raise ValueError("自定义指令请控制在 8,000 字符以内")


@dataclass
class ChatSession:
    id: str = field(default_factory=lambda: uuid4().hex)
    title: str = "新对话"
    created_at: str = field(default_factory=now)
    updated_at: str = field(default_factory=now)
    messages: list[dict[str, Any]] = field(default_factory=list)
    draft: str = ""
    context: dict[str, Any] | None = None

    def add(self, role: str, content: str, **metadata: Any) -> dict[str, Any]:
        message = {"role": role, "content": content, "created_at": now(), "status": "complete", **metadata}
        self.messages.append(message)
        if role == "user" and self.title == "新对话":
            self.title = " ".join(content.split())[:30] or "新对话"
        self.updated_at = now()
        return message

    def export_markdown(self) -> str:
        lines = [f"# {self.title}", "", f"创建于 {self.created_at}", ""]
        if self.context:
            lines.extend([f"行情摘要截至 {self.context['context_policy']['data_cutoff']}", ""])
        for message in self.messages:
            label = "你" if message["role"] == "user" else "AI"
            lines.extend([f"## {label}", "", message["content"], ""])
            if message.get("status") != "complete":
                lines.extend([f"*状态：{message.get('status')}*", ""])
        return "\n".join(lines)


class ChatStore:
    def __init__(self, root: Path | None = None):
        self.root = root or user_storage_dir() / "chat"
        self.warnings: list[str] = []

    def _path(self, session_id: str) -> Path:
        if len(session_id) != 32 or any(c not in "0123456789abcdef" for c in session_id):
            raise ValueError("无效会话 ID")
        return self.root / "sessions" / f"{session_id}.json"

    @staticmethod
    def _write(path: Path, value: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, suffix=".tmp", delete=False) as output:
                temporary = Path(output.name)
                json.dump(value, output, ensure_ascii=False, indent=2, allow_nan=False)
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def save(self, session: ChatSession) -> None:
        session.updated_at = now()
        self._write(self._path(session.id), asdict(session))

    def delete(self, session_id: str) -> None:
        self._path(session_id).unlink(missing_ok=True)

    def set_active(self, session_id: str) -> None:
        self._path(session_id)
        self._write(self.root / "workspace.json", {"active_session_id": session_id})

    def active_id(self) -> str | None:
        try:
            session_id = json.loads((self.root / "workspace.json").read_text(encoding="utf-8"))["active_session_id"]
            self._path(session_id)
            return session_id
        except (OSError, ValueError, TypeError, KeyError):
            return None

    def load_all(self) -> list[ChatSession]:
        sessions = []
        self.warnings.clear()
        for path in (self.root / "sessions").glob("*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                session = ChatSession(**payload)
                if path != self._path(session.id) or not isinstance(session.messages, list):
                    raise ValueError("会话格式无效")
                if not all(isinstance(value, str) for value in (session.title, session.created_at, session.updated_at, session.draft)):
                    raise ValueError("会话字段无效")
                for message in session.messages:
                    if message.get("role") not in {"user", "assistant"} or not isinstance(message.get("content"), str):
                        raise ValueError("消息格式无效")
                    if message.get("status") == "pending":
                        message["status"] = "stopped"
                        message["error"] = "上次会话意外中断，可重新生成"
                if session.context is not None:
                    if (not isinstance(session.context, dict)
                            or "data_cutoff" not in session.context.get("context_policy", {})
                            or not isinstance(session.context.get("instrument", {}).get("name"), str)):
                        raise ValueError("行情摘要无效")
                sessions.append(session)
            except (OSError, ValueError, TypeError, AttributeError):
                self.warnings.append(f"无法读取会话 {path.stem[:8]}，原文件已保留")
        return sorted(sessions, key=lambda item: item.updated_at, reverse=True)

    def load_settings(self) -> ChatSettings:
        path = self.root / "preferences.json"
        if not path.exists():
            return ChatSettings()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            settings = ChatSettings(**{key: payload[key] for key in ChatSettings.__dataclass_fields__ if key in payload})
            settings.validate()
            return settings
        except (OSError, ValueError, TypeError, AttributeError):
            self.warnings.append("模型设置无法读取，已使用默认值；原文件已保留")
            return ChatSettings()

    def save_settings(self, settings: ChatSettings) -> None:
        settings.validate()
        self._write(self.root / "preferences.json", asdict(settings))


def request_history(messages: list[dict], budget: int) -> tuple[list[dict[str, str]], int]:
    """Keep whole recent turns and the current question, never cut message text."""
    turns: list[list[dict[str, str]]] = []
    for message in messages:
        item = {"role": message["role"], "content": message["content"]}
        if item["role"] == "user":
            turns.append([item])
        elif turns and message.get("status", "complete") in {"complete", "stopped"} and item["content"]:
            # Regenerations retain every version locally; use the latest completed one.
            turns[-1] = [turns[-1][0], item]
    if not turns:
        raise ValueError("请输入问题")
    current = [turns[-1][0]]
    used = len(current[0]["content"])
    if used > budget:
        raise ValueError("当前问题超过上下文预算，请缩短问题或在模型设置中提高预算")
    included: list[list[dict[str, str]]] = []
    for turn in reversed(turns[:-1]):
        if len(turn) != 2:
            continue
        size = sum(len(item["content"]) for item in turn)
        if used + size > budget:
            break
        included.append(turn)
        used += size
    return [item for turn in reversed(included) for item in turn] + current, len(turns) - len(included) - 1
