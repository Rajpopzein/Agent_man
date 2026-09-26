import json
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _setup():
    suffix = str(uuid4())[:8]
    connection = client.post(
        "/api/ai/connections",
        json={
            "name": "Executive " + suffix,
            "provider_id": "lmstudio",
            "default_model": "executive-model",
        },
    )
    assert connection.status_code == 201

    project = client.post(
        "/api/projects",
        json={
            "name": "Executive Project " + suffix,
            "workspace_path": "D:\\AgentMan\\executive-tests\\" + suffix,
        },
    )
    assert project.status_code == 201

    workers = {}
    for role in ["Developer", "Tester"]:
        response = client.post(
            "/api/agents",
            json={
                "project_id": project.json()["id"],
                "name": role + " " + suffix,
                "role": role,
                "llm": {
                    "provider_id": "lmstudio",
                    "connection_id": connection.json()["id"],
                    "model": role.lower() + "-model",
                },
            },
        )
        assert response.status_code == 201
        workers[role] = response.json()

    configured = client.put(
        "/api/main-agent/projects/" + project.json()["id"] + "/config",
        json={
            "connection_id": connection.json()["id"],
            "model": "executive-model",
            "temperature": 0.2,
        },
    )
    assert configured.status_code == 200
    return project.json(), workers


def test_main_agent_delegates_and_returns_unified_answer(monkeypatch):
    project, workers = _setup()
    calls = {"count": 0}

    def fake_run_messages(agent, messages, endpoint=None):
        calls["count"] += 1
        if calls["count"] == 1:
            return json.dumps({
                "type": "delegate_agent",
                "agent_id": workers["Developer"]["id"],
                "task": "Implement the requested feature and verify it.",
            })
        return json.dumps({
            "type": "reply",
            "message": "I delegated implementation to Developer, reviewed the result, and the feature is complete.",
        })

    def fake_execute_agent(**kwargs):
        assert kwargs["agent"].id == workers["Developer"]["id"]
        return {
            "status": "completed",
            "text": "Feature implemented. Tests passed.",
            "steps": [{"tool": "run_tests", "status": "ok"}],
        }

    monkeypatch.setattr(
        "app.agents.executive.run_messages",
        fake_run_messages,
    )
    monkeypatch.setattr(
        "app.agents.executive.execute_agent",
        fake_execute_agent,
    )

    response = client.post(
        "/api/main-agent/projects/" + project["id"] + "/chat",
        json={
            "message": "Build the feature and make sure it works.",
            "allow_terminal": True,
            "allow_delete": False,
            "allow_network": False,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert "Developer" in body["text"]
    assert len(body["steps"]) == 1
    assert body["steps"][0]["type"] == "delegate_agent"

    messages = client.get(
        "/api/main-agent/projects/" + project["id"] + "/messages"
    )
    assert messages.status_code == 200
    assert [item["role"] for item in messages.json()][-2:] == [
        "user",
        "assistant",
    ]


def test_main_agent_can_reply_without_delegating(monkeypatch):
    project, _workers = _setup()

    monkeypatch.setattr(
        "app.agents.executive.run_messages",
        lambda agent, messages, endpoint=None: json.dumps({
            "type": "reply",
            "message": "All systems are available.",
        }),
    )

    response = client.post(
        "/api/main-agent/projects/" + project["id"] + "/chat",
        json={
            "message": "What can you do?",
            "allow_terminal": False,
            "allow_delete": False,
            "allow_network": False,
        },
    )
    assert response.status_code == 200
    assert response.json()["text"] == "All systems are available."
    assert response.json()["steps"] == []
