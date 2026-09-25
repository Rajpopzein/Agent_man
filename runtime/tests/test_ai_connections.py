from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_provider_catalog_contains_supported_connections():
    response = client.get("/api/ai/providers")
    assert response.status_code == 200
    ids = {item["id"] for item in response.json()}
    assert {"lmstudio", "ollama", "gemini", "openai", "openai-compatible"} <= ids


def test_local_connection_can_be_linked_to_agent():
    suffix = str(uuid4())[:8]
    connection = client.post(
        "/api/ai/connections",
        json={
            "name": "LM Studio " + suffix,
            "provider_id": "lmstudio",
            "default_model": "test-model",
        },
    )
    assert connection.status_code == 201
    connection_body = connection.json()
    assert connection_body["endpoint"] == "http://localhost:1234/v1"
    assert connection_body["has_secret"] is False

    project = client.post(
        "/api/projects",
        json={
            "name": "AI Link " + suffix,
            "workspace_path": "D:\\AgentMan\\tests\\" + suffix,
        },
    )
    assert project.status_code == 201

    agent = client.post(
        "/api/agents",
        json={
            "project_id": project.json()["id"],
            "name": "Developer " + suffix,
            "role": "Developer",
            "llm": {
                "provider_id": "lmstudio",
                "connection_id": connection_body["id"],
                "model": "test-model",
            },
        },
    )
    assert agent.status_code == 201
    assert agent.json()["llm"]["connection_id"] == connection_body["id"]
    assert agent.json()["llm"]["endpoint"] == "http://localhost:1234/v1"

    blocked = client.delete(
        "/api/ai/connections/" + connection_body["id"]
    )
    assert blocked.status_code == 409


def test_cloud_connection_requires_key():
    response = client.post(
        "/api/ai/connections",
        json={
            "name": "Gemini without key",
            "provider_id": "gemini",
        },
    )
    assert response.status_code == 422
