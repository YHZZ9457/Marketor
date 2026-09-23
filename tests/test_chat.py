from __future__ import annotations

import io
import json
from urllib.error import HTTPError

import pytest

from csi300_service.chat_client import ChatCancellation, ChatCancelled, StreamingChatClient
from csi300_service.chat_store import ChatSession, ChatSettings, ChatStore, request_history


def sse(*events):
    return io.BytesIO("".join("data: " + (event if isinstance(event, str) else json.dumps(event, ensure_ascii=False)) + "\n\n" for event in events).encode())


def test_stream_emits_unicode_chunks_and_usage_then_closes_response():
    response = sse(
        {"choices": [{"delta": {"reasoning_content": "thinking"}}]},
        {"choices": [{"delta": {"content": "你好"}}]},
        {"choices": [{"delta": {"content": " 🌍"}, "finish_reason": "length"}]},
        {"choices": [], "usage": {"completion_tokens": 12}}, "[DONE]",
    )
    def opener(request, timeout):
        body = json.loads(request.data)
        assert body["stream"] is True
        assert body["max_tokens"] == 4096
        assert body["messages"][1]["content"] == "question"
        assert timeout == 45
        return response
    parts, phases = [], []
    client = StreamingChatClient(api_key="secret", opener=opener)
    result = client.stream_chat("system", [{"role": "user", "content": "question"}], on_token=parts.append, cancellation=ChatCancellation(), on_thinking=lambda: phases.append(True))
    assert parts == ["你好", " 🌍"]
    assert result.text == "你好 🌍" and result.finish_reason == "length"
    assert result.usage == {"completion_tokens": 12}
    assert phases == [True] and response.closed


def test_sse_multiline_and_comments():
    response = io.BytesIO(b': ping\n\ndata: {"choices":\ndata: [{"delta":{"content":"hello"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
    parts = []
    result = StreamingChatClient(api_key="key", opener=lambda *a, **k: response).stream_chat("sys", [], on_token=parts.append, cancellation=ChatCancellation())
    assert result.text == "hello"


def test_nonstreaming_compatible_server_is_supported():
    response = io.BytesIO(json.dumps({"choices": [{"message": {"content": "hello"}, "finish_reason": "stop"}]}).encode())
    result = StreamingChatClient(api_key="key", opener=lambda *a, **k: response).stream_chat("sys", [], on_token=lambda _: None, cancellation=ChatCancellation())
    assert result.text == "hello"


def test_truncated_stream_keeps_delivered_text_and_reports_failure():
    response = sse({"choices": [{"delta": {"content": "partial"}}]})
    parts = []
    with pytest.raises(RuntimeError, match="提前中断"):
        StreamingChatClient(api_key="key", opener=lambda *a, **k: response).stream_chat("sys", [], on_token=parts.append, cancellation=ChatCancellation())
    assert parts == ["partial"] and response.closed


def test_stop_interrupts_stream_without_emitting_more_tokens():
    response = sse({"choices": [{"delta": {"content": "first"}}]}, {"choices": [{"delta": {"content": "second"}}]}, "[DONE]")
    cancellation = ChatCancellation()
    parts = []
    def receive(part):
        parts.append(part)
        cancellation.cancel()
    with pytest.raises(ChatCancelled):
        StreamingChatClient(api_key="key", opener=lambda *a, **k: response).stream_chat("sys", [], on_token=receive, cancellation=cancellation)
    assert parts == ["first"]


def test_cancel_before_connect_never_sends_request():
    cancellation = ChatCancellation()
    cancellation.cancel()
    def opener(*a, **k):
        pytest.fail("cancelled request connected")
    with pytest.raises(ChatCancelled):
        StreamingChatClient(api_key="secret", opener=opener).stream_chat("sys", [], on_token=lambda _: None, cancellation=cancellation)


@pytest.mark.parametrize("exception", [HTTPError("https://example.com", 401, "secret", {}, None), RuntimeError("secret")])
def test_transport_errors_are_actionable_and_redact_credentials(exception):
    def opener(*a, **k):
        raise exception
    with pytest.raises(RuntimeError) as error:
        StreamingChatClient(api_key="secret", opener=opener).stream_chat("sys", [], on_token=lambda _: None, cancellation=ChatCancellation())
    assert "secret" not in str(error.value)


def test_sessions_settings_and_drafts_round_trip(tmp_path):
    store = ChatStore(tmp_path)
    session = ChatSession(draft="unfinished question")
    session.add("user", "第一条问题")
    session.add("assistant", "# 答案\n```python\nprint(1)\n```", model="my-model")
    store.save(session)
    saved = store.load_all()[0]
    assert saved == session
    assert "```python" in saved.export_markdown()
    settings = ChatSettings(model="custom", system_prompt="简洁回答")
    store.save_settings(settings)
    assert store.load_settings() == settings
    assert "api_key" not in (tmp_path / "preferences.json").read_text(encoding="utf-8")
    store.delete(session.id)
    assert not store.load_all()


def test_interrupted_sessions_recover_and_corrupt_files_remain(tmp_path):
    store = ChatStore(tmp_path)
    session = ChatSession()
    session.add("user", "question")
    session.add("assistant", "partial", status="pending")
    store.save(session)
    broken = tmp_path / "sessions" / "broken.json"
    broken.write_text("{", encoding="utf-8")
    recovered = store.load_all()[0]
    assert recovered.messages[-1]["status"] == "stopped"
    assert recovered.messages[-1]["content"] == "partial"
    assert store.warnings and broken.exists()


def test_failed_atomic_save_preserves_original(tmp_path, monkeypatch):
    store = ChatStore(tmp_path)
    session = ChatSession(title="Original")
    store.save(session)
    def fail(*_):
        raise OSError("disk error")
    monkeypatch.setattr("csi300_service.chat_store.os.replace", fail)
    session.title = "Changed"
    with pytest.raises(OSError):
        store.save(session)
    assert store.load_all()[0].title == "Original"


def test_history_keeps_whole_turns_and_latest_regenerated_answer():
    session = ChatSession()
    for index in range(20):
        session.add("user", f"question {index}")
        session.add("assistant", f"answer {index}")
    session.add("assistant", "new answer")
    session.add("user", "latest question")
    messages, omitted = request_history(session.messages, 10000)
    assert len(messages) == 41 and omitted == 0
    assert messages[-2]["content"] == "new answer"
    short, omitted = request_history(session.messages, 40)
    assert short[-1]["content"] == "latest question"
    assert omitted > 0
    assert len(short) % 2 == 1
    assert all(m["content"] in {original["content"] for original in session.messages} for m in short)


def test_failed_answers_are_not_silently_used_as_context():
    messages = [{"role": "user", "content": "old"}, {"role": "assistant", "content": "partial", "status": "error"}, {"role": "user", "content": "new"}]
    selected, omitted = request_history(messages, 1000)
    assert selected == [{"role": "user", "content": "new"}]
    assert omitted == 1


@pytest.mark.parametrize("settings", [ChatSettings(model=""), ChatSettings(temperature=float("nan")), ChatSettings(base_url="file:///secret"), ChatSettings(base_url="https://host/?key=secret"), ChatSettings(max_tokens=0)])
def test_settings_validation(settings):
    with pytest.raises(ValueError):
        settings.validate()


def test_session_paths_cannot_escape_storage(tmp_path):
    with pytest.raises(ValueError):
        ChatStore(tmp_path).delete("../../outside")


def test_stopped_reply_can_be_continued_and_active_session_is_restored(tmp_path):
    store = ChatStore(tmp_path)
    first, second = ChatSession(), ChatSession()
    for session in (first, second):
        store.save(session)
    store.set_active(first.id)
    assert ChatStore(tmp_path).active_id() == first.id
    first.add("user", "Explain this")
    first.add("assistant", "First point", status="stopped")
    first.add("user", "Continue")
    messages, _ = request_history(first.messages, 1000)
    assert messages[-2]["content"] == "First point"


def test_models_are_fetched_from_configured_endpoint():
    def opener(request, timeout):
        assert request.full_url == "https://example.com/v1/models"
        return io.BytesIO(b'{"data":[{"id":"custom-model"},{"id":"custom-model"}]}')
    client = StreamingChatClient(api_key="key", base_url="https://example.com/v1", opener=opener)
    assert client.list_models() == ["custom-model"]


def test_real_http_stream_delivers_first_token_before_completion():
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Event, Thread
    first_received, streamed = Event(), Event()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            assert payload["stream"]
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(b'data: {"choices":[{"delta":{"content":"first"}}]}\n\n')
            self.wfile.flush()
            if first_received.wait(3):
                streamed.set()
            self.wfile.write(b'data: {"choices":[{"delta":{"content":" second"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
            self.wfile.flush()
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        client = StreamingChatClient(api_key="test-only", base_url=f"http://127.0.0.1:{server.server_port}")
        result = client.stream_chat("system", [{"role": "user", "content": "test"}], cancellation=ChatCancellation(), on_token=lambda text: first_received.set())
        assert streamed.is_set()
        assert result.text == "first second"
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)
