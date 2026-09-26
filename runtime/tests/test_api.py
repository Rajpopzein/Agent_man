from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_project_agent_flow():
    project = client.post(
        "/api/projects",
        json={"name": "Test", "workspace_path": "D:\\AgentMan\\test"},
    )
    assert project.status_code == 201
    agent = client.post(
        "/api/agents",
        json={
            "project_id": project.json()["id"],
            "name": "Developer",
            "role": "Developer",
            "llm": {
                "provider_id": "lmstudio",
                "connection_id": "local",
                "model": "test-model",
                "endpoint": "http://localhost:1234/v1",
            },
        },
    )
    assert agent.status_code == 201
    assert agent.json()["llm"]["endpoint"] == "http://localhost:1234/v1"
    listed = client.get("/api/projects/" + project.json()["id"] + "/agents")
    assert listed.status_code == 200
    assert listed.json()[0]["llm"]["endpoint"] == "http://localhost:1234/v1"



def test_unused_agent_can_be_deleted():
    project = client.post(
        "/api/projects",
        json={
            "name": "Delete Agent Project",
            "workspace_path": "D:\\AgentMan\\delete-agent",
        },
    )
    assert project.status_code == 201

    agent = client.post(
        "/api/agents",
        json={
            "project_id": project.json()["id"],
            "name": "Disposable",
            "role": "Developer",
            "llm": {
                "provider_id": "lmstudio",
                "connection_id": "local",
                "model": "test-model",
                "endpoint": "http://localhost:1234/v1",
            },
        },
    )
    assert agent.status_code == 201

    deleted = client.delete("/api/agents/" + agent.json()["id"])
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True

    listed = client.get(
        "/api/projects/" + project.json()["id"] + "/agents"
    )
    assert listed.status_code == 200
    assert agent.json()["id"] not in {
        item["id"] for item in listed.json()
    }


def test_agent_delete_is_blocked_when_history_references_it():
    project = client.post(
        "/api/projects",
        json={
            "name": "Protected Agent Project",
            "workspace_path": "D:\\AgentMan\\protected-agent",
        },
    )
    assert project.status_code == 201

    agent_ids = []
    for name in ["Architect", "Developer"]:
        agent = client.post(
            "/api/agents",
            json={
                "project_id": project.json()["id"],
                "name": name,
                "role": name,
                "llm": {
                    "provider_id": "lmstudio",
                    "connection_id": "local",
                    "model": "test-model",
                    "endpoint": "http://localhost:1234/v1",
                },
            },
        )
        assert agent.status_code == 201
        agent_ids.append(agent.json()["id"])

    task = client.post(
        "/api/multi-agent/tasks",
        json={
            "project_id": project.json()["id"],
            "title": "Protected history",
            "prompt": "Collaborate",
            "agent_ids": agent_ids,
            "max_rounds": 2,
        },
    )
    assert task.status_code == 201

    blocked = client.delete("/api/agents/" + agent_ids[0])
    assert blocked.status_code == 409
    assert "multi-agent" in blocked.json()["detail"]
