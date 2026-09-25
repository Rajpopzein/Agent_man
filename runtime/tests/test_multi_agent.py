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


def test_multi_agent_peers_complete_without_coordinator(monkeypatch):
    project, agents = _create_peer_setup()

    def fake_run_messages(agent, messages, endpoint=None):
        return json.dumps(
            {
                "type": "final",
                "content": agent.role + " completed its peer contribution.",
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
            "title": "Implement peer capability",
            "prompt": "Review the implementation from your own role.",
            "agent_ids": [agent["id"] for agent in agents],
            "max_rounds": 3,
        },
    )
    assert created.status_code == 201
    assert len(created.json()["participants"]) == 2
    assert created.json()["messages"] == []

    run = client.post(
        "/api/multi-agent/tasks/" + created.json()["id"] + "/run",
        json={"allow_terminal": False},
    )
    assert run.status_code == 200
    body = run.json()
    assert body["status"] == "completed"
    assert len(body["participants"]) == 2
    assert all(
        participant["status"] == "completed"
        for participant in body["participants"]
    )

    finals = [
        message
        for message in body["messages"]
        if message["kind"] == "final"
    ]
    assert len(finals) == 2
    assert {message["agent_id"] for message in finals} == {
        agent["id"] for agent in agents
    }
