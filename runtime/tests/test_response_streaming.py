import io
import json
from types import SimpleNamespace

import pytest

from app.agents.protocol import response_preview, special_action
from app.agents.runner import run_messages
from app.events.bus import EventBus
from app.providers.gemini import GeminiProvider
from app.providers.ollama import OllamaProvider
from app.providers.registry import get_provider
from app.providers.streaming import stream_json


@pytest.mark.parametrize("raw", [
    '<|tool_call>call:list_serial_ports{}<tool_call|>',
    r'<|tool\_call>call:list\_serial\_ports{}\<tool\_call|>',
])
def test_local_tool_template_is_parsed_without_displaying_it(raw):
    assert special_action(raw) == {"type": "tool", "tool": "list_serial_ports", "args": {}}
    assert response_preview(raw, structured=True) == ""


def test_tool_template_preserves_argument_escapes():
    raw = '<|tool_call>call:read_file' + json.dumps({"path": r"folder\_file.txt"}) + '<tool_call|>'
    assert special_action(raw)["args"]["path"] == r"folder\_file.txt"
    assert special_action('<|tool_call>call:serial_open{broken}<tool_call|>')["type"] == "invalid_action"


@pytest.mark.parametrize("kind,field", [("reply", "message"), ("final", "message"), ("message", "content"), ("final", "content")])
def test_preview_decodes_incremental_reply_not_json(kind, field):
    raw = json.dumps({"type": kind, field: 'Connected\nESP32 "ready" ☃'})
    previews = [response_preview(raw[:index], structured=True) for index in range(1, len(raw) + 1)]
    assert "Connected" in previews
    assert previews[-1] == 'Connected\nESP32 "ready" ☃'
    assert all(not item.startswith("{") for item in previews)


def test_preview_does_not_leak_actions_or_reasoning():
    for raw in [
        '{"type":"tool","tool":"serial_open","args":{"message":"secret","device":"COM2"}}',
        '<think>private reasoning</think>',
        '{"type":"reply","message":"<|tool_call>call:list_serial_ports{}<tool_call|>"}',
    ]:
        assert response_preview(raw, structured=True) == ""
    marker_reply = json.dumps({"type": "reply", "message": "<|tool_call>call:list_serial_ports{}<tool_call|>"})
    assert all(response_preview(marker_reply[:end], structured=True) == "" for end in range(len(marker_reply) + 1))


def test_transport_reads_sse_and_ndjson_incrementally(monkeypatch):
    body = b': heartbeat\n\ndata: {"value": 1}\n\ndata: {"value": 2}\n\ndata: [DONE]\n\n'
    monkeypatch.setattr("app.providers.streaming.urlopen", lambda *a, **k: io.BytesIO(body))
    output = stream_json("http://example.invalid", {})
    assert next(output) == {"value": 1}
    assert list(output) == [{"value": 2}]
    body = b'{"message":{"content":"hello"}}\n{"done":true}\n'
    assert len(list(stream_json("http://example.invalid", {}, ndjson=True))) == 2
    body = b'data: {"error":"failed"}\n\n'
    with pytest.raises(RuntimeError, match="failed"):
        list(stream_json("http://example.invalid", {}))


@pytest.mark.parametrize("provider,wire,expected_url", [
    (get_provider("lmstudio"), b'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\ndata: {"choices":[{"delta":{"content":" world"}}]}\n\ndata: [DONE]\n\n', '/chat/completions'),
    (OllamaProvider(), b'{"message":{"content":"Hello"}}\n{"message":{"content":" world"},"done":true}\n', '/api/chat'),
    (GeminiProvider(), b'data: {"candidates":[{"content":{"parts":[{"text":"hidden","thought":true},{"text":"Hello"}]}}]}\n\ndata: {"candidates":[{"content":{"parts":[{"text":" world"}]}}]}\n\n', ':streamGenerateContent?alt=sse'),
])
def test_provider_stream_protocols(monkeypatch, provider, wire, expected_url):
    def open_request(request, timeout):
        assert request.full_url.endswith(expected_url)
        payload = json.loads(request.data)
        if not isinstance(provider, GeminiProvider):
            assert payload["stream"] is True
        return io.BytesIO(wire)
    monkeypatch.setattr("app.providers.streaming.urlopen", open_request)
    assert list(provider.stream_chat(model="test", messages=[{"role": "user", "content": "hi"}], api_key="test")) == ["Hello", " world"]


@pytest.mark.parametrize("role", ["Executive", "Developer", "Peer", "Tester"])
def test_runner_publishes_before_provider_finishes(monkeypatch, role):
    bus = EventBus()
    clock = iter(range(100))
    monkeypatch.setattr("app.agents.runner.events", bus)
    monkeypatch.setattr("app.agents.runner.perf_counter", lambda: next(clock))
    monkeypatch.setattr("app.agents.runner._write_log", lambda **kwargs: None)
    class StreamingProvider:
        def stream_chat(self, **kwargs):
            yield '{"type":"reply","message":"Hello'
            assert bus.recent()[-1]["type"] == "agent.response.delta"
            assert bus.recent()[-1]["text"] == "Hello"
            yield ' world"}'
    monkeypatch.setattr("app.agents.runner.get_provider", lambda _: StreamingProvider())
    agent = SimpleNamespace(id="a", project_id="p", name="Agent", role=role, provider_id="fake", model="test", endpoint=None, temperature_milli=200)
    result = run_messages(agent, [{"role": "system", "content": "Return exactly one JSON object"}])
    assert json.loads(result)["message"] == "Hello world"
    emitted = bus.recent()
    assert emitted[-1]["type"] == "agent.response.completed"
    assert emitted[-1]["text"] == "Hello world"
    assert len({item["response_id"] for item in emitted}) == 1
    assert all(item["project_id"] == "p" and item["agent_id"] == "a" for item in emitted)


def test_runner_reports_stream_failure(monkeypatch):
    bus = EventBus()
    monkeypatch.setattr("app.agents.runner.events", bus)
    monkeypatch.setattr("app.agents.runner._write_log", lambda **kwargs: None)
    class BrokenProvider:
        def stream_chat(self, **kwargs):
            yield '{"type":"reply","message":"Partial'
            raise RuntimeError("connection lost")
    monkeypatch.setattr("app.agents.runner.get_provider", lambda _: BrokenProvider())
    agent = SimpleNamespace(id="a", project_id="p", provider_id="fake", model="test", endpoint=None, temperature_milli=200)
    with pytest.raises(RuntimeError, match="connection lost"):
        run_messages(agent, [])
    assert bus.recent()[-1]["type"] == "agent.response.error"


def test_live_sse_delivers_partial_response_before_completion(monkeypatch):
    import socket
    import threading
    import time
    import httpx
    import uvicorn
    from fastapi import FastAPI
    from app.api.routes import stream_events

    bus = EventBus()
    release = threading.Event()
    monkeypatch.setattr("app.agents.runner.events", bus)
    monkeypatch.setattr("app.api.routes.events", bus)
    monkeypatch.setattr("app.agents.runner._write_log", lambda **kwargs: None)
    clock = iter(range(100))
    monkeypatch.setattr("app.agents.runner.perf_counter", lambda: next(clock))

    class StreamingProvider:
        def stream_chat(self, **kwargs):
            yield '{"type":"reply","message":"Connected'
            assert release.wait(5), "Client did not receive the partial response"
            yield ' to ESP32"}'

    monkeypatch.setattr("app.agents.runner.get_provider", lambda _: StreamingProvider())
    agent = SimpleNamespace(id="a", project_id="p", provider_id="fake", model="test", endpoint=None, temperature_milli=200)
    app = FastAPI()
    app.add_api_route("/events", stream_events)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", timeout_graceful_shutdown=1))
    server_thread = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
    worker = threading.Thread(target=lambda: run_messages(agent, [{"role": "system", "content": "Return exactly one JSON object"}]), daemon=True)
    server_thread.start()
    try:
        deadline = time.monotonic() + 5
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started
        with httpx.stream("GET", f"http://127.0.0.1:{port}/events?project_id=p", timeout=5) as response:
            assert response.status_code == 200
            worker.start()
            seen = []
            for line in response.iter_lines():
                if not line.startswith("data: "):
                    continue
                event = json.loads(line[6:])
                seen.append(event)
                if event["type"] == "agent.response.delta" and not release.is_set():
                    assert event["text"] == "Connected"
                    assert worker.is_alive()
                    release.set()
                if event["type"] == "agent.response.completed":
                    assert event["text"] == "Connected to ESP32"
                    break
            assert any(item["type"] == "agent.response.delta" for item in seen)
    finally:
        release.set()
        if worker.ident:
            worker.join(5)
        server.should_exit = True
        # Wake the idle SSE waiter so shutdown doesn't wait for a heartbeat.
        bus.emit("test.finished", project_id="p")
        server_thread.join(5)
        listener.close()
