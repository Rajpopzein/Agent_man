from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from app.agents.runner import run_messages
from app.main import app

client = TestClient(app)


class FakeProvider:
    def chat(
        self,
        *,
        model,
        messages,
        endpoint=None,
        api_key=None,
        temperature=0.2,
    ):
        assert api_key is None
        assert messages[-1]["content"] == "hello"
        return "logged response"


def test_llm_call_is_logged_and_can_be_cleared(monkeypatch):
    suffix = str(uuid4())[:8]
    project = client.post(
        "/api/projects",
        json={
            "name": "LLM Logs " + suffix,
            "workspace_path": "D:\\AgentMan\\llm-logs\\" + suffix,
        },
    )
    assert project.status_code == 201
    project_id = project.json()["id"]

    monkeypatch.setattr(
        "app.agents.runner.get_provider",
        lambda provider_id: FakeProvider(),
    )

    agent = SimpleNamespace(
        id="test-agent-" + suffix,
        project_id=project_id,
        name="Log Tester",
        role="Tester",
        provider_id="fake",
        model="fake-model",
        endpoint="http://example.invalid/v1",
        temperature_milli=200,
    )

    result = run_messages(
        agent,
        [{"role": "user", "content": "hello"}],
    )
    assert result == "logged response"

    logs = client.get(
        "/api/llm-logs/projects/" + project_id + "?limit=10"
    )
    assert logs.status_code == 200
    body = logs.json()
    assert len(body) >= 1
    latest = body[0]
    assert latest["actor_name"] == "Log Tester"
    assert latest["actor_role"] == "Tester"
    assert latest["provider_id"] == "fake"
    assert latest["model"] == "fake-model"
    assert latest["status"] == "success"
    assert "hello" in latest["request_json"]
    assert latest["response_text"] == "logged response"
    assert latest["error_text"] == ""

    cleared = client.delete(
        "/api/llm-logs/projects/" + project_id
    )
    assert cleared.status_code == 200
    assert cleared.json()["cleared"] is True

    after = client.get(
        "/api/llm-logs/projects/" + project_id + "?limit=10"
    )
    assert after.status_code == 200
    assert after.json() == []
