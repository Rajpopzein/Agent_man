import json
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _create_peer_setup():
    suffix = str(uuid4())[:8]
    connection = client.post(
        "/api/ai/connections",
        json={
            "name": "Peers " + suffix,
            "provider_id": "lmstudio",
            "default_model": "test-model",
        },
    )
    assert connection.status_code == 201

    project = client.post(
        "/api/projects",
        json={
            "name": "Peer Project " + suffix,
            "workspace_path": "D:\\AgentMan\\peer-tests\\" + suffix,
        },
    )
    assert project.status_code == 201

    agents = []
    for role in ["Architect", "Developer"]:
        response = client.post(
            "/api/agents",
            json={
                "project_id": project.json()["id"],
                "name": role + " " + suffix,
                "role": role,
                "llm": {
                    "provider_id": "lmstudio",
                    "connection_id": connection.json()["id"],
                    "model": "test-model",
                },
            },
        )
        assert response.status_code == 201
        agents.append(response.json())

    return project.json(), agents


def test_multi_agent_task_requires_two_different_agents():
    project, agents = _create_peer_setup()
    response = client.post(
        "/api/multi-agent/tasks",
        json={
            "project_id": project["id"],
            "title": "Invalid peer task",
            "prompt": "Work together",
            "agent_ids": [agents[0]["id"], agents[0]["id"]],
            "max_rounds": 2,
        },
    )
    assert response.status_code == 422


def test_multi_agent_requires_stable_peer_completion(monkeypatch):
    project, agents = _create_peer_setup()

    def fake_run_messages(agent, messages, endpoint=None):
        return json.dumps(
            {
                "type": "final",
                "content": agent.role + " confirms the shared job is complete.",
            }
        )

    monkeypatch.setattr(
        "app.agents.multi_agent.run_messages",
        fake_run_messages,
    )

    created = client.post(
        "/api/multi-agent/tasks",
        json={
            "project_id": project["id"],
            "title": "Stable peer completion",
            "prompt": "Review the implementation from your own role.",
            "agent_ids": [agent["id"] for agent in agents],
            "max_rounds": 4,
        },
    )
    assert created.status_code == 201

    run = client.post(
        "/api/multi-agent/tasks/" + created.json()["id"] + "/run",
        json={
            "allow_terminal": False,
            "allow_delete": False,
        },
    )
    assert run.status_code == 200
    body = run.json()
    assert body["status"] == "completed"
    assert body["current_round"] == 2
    assert all(
        participant["status"] == "completed"
        for participant in body["participants"]
    )

    finals = [
        message
        for message in body["messages"]
        if message["kind"] == "final"
    ]
    assert len(finals) == 4
    assert {message["round_number"] for message in finals} == {1, 2}


def test_peer_concern_reopens_completion_until_stable(monkeypatch):
    project, agents = _create_peer_setup()
    calls = {"Architect": 0, "Developer": 0}

    def fake_run_messages(agent, messages, endpoint=None):
        calls[agent.role] += 1
        if agent.role == "Developer" and calls[agent.role] == 1:
            return json.dumps(
                {
                    "type": "message",
                    "content": "I found an unresolved implementation issue.",
                }
            )
        return json.dumps(
            {
                "type": "final",
                "content": agent.role + " now confirms completion.",
            }
        )

    monkeypatch.setattr(
        "app.agents.multi_agent.run_messages",
        fake_run_messages,
    )

    created = client.post(
        "/api/multi-agent/tasks",
        json={
            "project_id": project["id"],
            "title": "Reopen until complete",
            "prompt": "Continue collaborating until no peer sees unresolved work.",
            "agent_ids": [agent["id"] for agent in agents],
            "max_rounds": 5,
        },
    )
    assert created.status_code == 201

    run = client.post(
        "/api/multi-agent/tasks/" + created.json()["id"] + "/run",
        json={
            "allow_terminal": False,
            "allow_delete": False,
        },
    )
    assert run.status_code == 200
    body = run.json()
    assert body["status"] == "completed"
    assert body["current_round"] == 3
    assert calls["Architect"] == 3
    assert calls["Developer"] == 3
    assert any(
        message["kind"] == "message"
        and "unresolved" in message["content"]
        for message in body["messages"]
    )


def test_round_limit_can_be_extended(monkeypatch):
    project, agents = _create_peer_setup()

    def fake_run_messages(agent, messages, endpoint=None):
        return json.dumps(
            {
                "type": "message",
                "content": agent.role + " still has work to review.",
            }
        )

    monkeypatch.setattr(
        "app.agents.multi_agent.run_messages",
        fake_run_messages,
    )

    created = client.post(
        "/api/multi-agent/tasks",
        json={
            "project_id": project["id"],
            "title": "Long peer task",
            "prompt": "Keep reviewing until complete.",
            "agent_ids": [agent["id"] for agent in agents],
            "max_rounds": 2,
        },
    )
    assert created.status_code == 201

    first = client.post(
        "/api/multi-agent/tasks/" + created.json()["id"] + "/run",
        json={
            "allow_terminal": False,
            "allow_delete": False,
        },
    )
    assert first.status_code == 200
    assert first.json()["status"] == "round_limit"
    assert first.json()["current_round"] == 2

    blocked = client.post(
        "/api/multi-agent/tasks/" + created.json()["id"] + "/run",
        json={
            "allow_terminal": False,
            "allow_delete": False,
        },
    )
    assert blocked.status_code == 409

    extended = client.post(
        "/api/multi-agent/tasks/" + created.json()["id"] + "/run",
        json={
            "allow_terminal": False,
            "allow_delete": False,
            "extend_rounds": 2,
        },
    )
    assert extended.status_code == 200
    assert extended.json()["max_rounds"] == 4
    assert extended.json()["current_round"] == 4
    assert extended.json()["status"] == "round_limit"
