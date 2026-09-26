from types import SimpleNamespace

from app.agents.runner import run_messages
from app.events.bus import events


class ChunkedProvider:
    def stream_chat(self, **kwargs):
        yield '{"type":"reply","message":"Hel'
        yield 'lo '
        yield 'world"}'

    def chat(self, **kwargs):
        raise AssertionError("stream_chat should be used")


def test_runner_emits_incremental_user_facing_text(monkeypatch):
    monkeypatch.setattr(
        "app.agents.runner.get_provider",
        lambda provider_id: ChunkedProvider(),
    )

    agent = SimpleNamespace(
        id="main-agent:test-project",
        project_id="test-project",
        name="Agent Man",
        role="Executive",
        provider_id="fake",
        model="fake-model",
        endpoint="http://example.invalid",
        temperature_milli=200,
    )

    cursor = events.current_sequence()
    result = run_messages(
        agent,
        [
            {
                "role": "system",
                "content": "Return exactly one JSON object and no markdown.",
            },
            {
                "role": "user",
                "content": "Say hello.",
            },
        ],
    )

    assert result == '{"type":"reply","message":"Hello world"}'

    _, emitted = events.wait_since(
        cursor,
        timeout=0,
        project_id="test-project",
    )
    response_events = [
        event
        for event in emitted
        if str(event["type"]).startswith("agent.response.")
    ]

    assert response_events[0]["type"] == "agent.response.started"
    assert response_events[0]["provider_id"] == "fake"
    assert response_events[0]["model"] == "fake-model"
    assert response_events[0]["agent_role"] == "Executive"

    deltas = [
        event["text"]
        for event in response_events
        if event["type"] == "agent.response.delta"
    ]
    assert deltas
    assert deltas[0].startswith("Hel")

    completed = [
        event
        for event in response_events
        if event["type"] == "agent.response.completed"
    ]
    assert completed
    assert completed[-1]["text"] == "Hello world"
    assert isinstance(completed[-1]["duration_ms"], int)
    assert completed[-1]["duration_ms"] >= 0
