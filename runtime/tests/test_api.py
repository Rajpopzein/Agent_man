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
