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
            "name": "Extensions " + suffix,
            "provider_id": "lmstudio",
            "default_model": "worker-model",
        },
    )
    assert connection.status_code == 201

    project = client.post(
        "/api/projects",
        json={
            "name": "Extensions " + suffix,
            "workspace_path": "D:\\AgentMan\\extensions-tests\\" + suffix,
        },
    )
    assert project.status_code == 201

    agent = client.post(
        "/api/agents",
        json={
            "project_id": project.json()["id"],
            "name": "Developer " + suffix,
            "role": "Developer",
            "context": "Implement requested changes.",
            "llm": {
                "provider_id": "lmstudio",
                "connection_id": connection.json()["id"],
                "model": "worker-model",
            },
        },
    )
    assert agent.status_code == 201
    return project.json(), agent.json()


def test_skill_crud_assignment_and_worker_prompt_injection(monkeypatch):
    project, agent = _setup()
    skill = client.post(
        "/api/extensions/projects/" + project["id"] + "/skills",
        json={
            "name": "Frontend Design",
            "slug": "frontend-design",
            "description": "Professional frontend implementation rules.",
            "content": (
                "# Purpose\n"
                "Build readable professional interfaces.\n\n"
                "## Instructions\n"
                "- Keep typography readable.\n"
                "- Validate responsive layouts."
            ),
        },
    )
    assert skill.status_code == 201

    assigned = client.put(
        "/api/extensions/agents/"
        + agent["id"]
        + "/skills/"
        + skill.json()["id"]
    )
    assert assigned.status_code == 200
    assert assigned.json()["assigned"] is True

    captured = []
    calls = {"count": 0}

    def respond(agent_proxy, messages, endpoint=None):
        calls["count"] += 1
        captured.append(messages[0]["content"])
        return json.dumps({
            "type": "final",
            "verified": True,
            "progress": "Checking the finished work.",
            "next_step": "Report the verified result.",
            "message": "The task is complete.",
        })

    monkeypatch.setattr(
        "app.agents.executor.run_messages",
        respond,
    )

    response = client.post(
        "/api/agents/" + agent["id"] + "/execute",
        json={"prompt": "Improve the frontend."},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert calls["count"] == 2
    assert "ASSIGNED SKILLS:" in captured[0]
    assert "### SKILL.md: frontend-design" in captured[0]
    assert "Keep typography readable." in captured[0]


def test_connector_metadata_never_returns_api_key(monkeypatch):
    project, _ = _setup()

    class FakeSecrets:
        def __init__(self):
            self.values = {}

        def set(self, key, value):
            self.values[key] = value

        def delete(self, key):
            self.values.pop(key, None)

    fake = FakeSecrets()
    monkeypatch.setattr("app.api.extensions.secrets", fake)

    response = client.post(
        "/api/extensions/projects/" + project["id"] + "/connectors",
        json={
            "name": "Groww",
            "kind": "groww",
            "base_url": "",
            "config": {"mode": "read-only"},
            "api_key": "super-secret-groww-token",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["kind"] == "groww"
    assert body["has_secret"] is True
    assert "api_key" not in body
    assert "super-secret-groww-token" not in json.dumps(body)

    listed = client.get(
        "/api/extensions/projects/" + project["id"] + "/connectors"
    )
    assert listed.status_code == 200
    payload = json.dumps(listed.json())
    assert "super-secret-groww-token" not in payload
    assert listed.json()[0]["has_secret"] is True


def test_extension_tools_are_executive_only():
    project, agent = _setup()

    executive = client.get(
        "/api/tools/main-agent/" + project["id"]
    )
    worker = client.get(
        "/api/tools/agents/" + agent["id"]
    )
    assert executive.status_code == 200
    assert worker.status_code == 200

    executive_by_name = {
        item["name"]: item
        for item in executive.json()
    }
    worker_by_name = {
        item["name"]: item
        for item in worker.json()
    }
    names = {
        "api_list_skills",
        "api_create_skill",
        "api_assign_skill",
        "api_list_connectors",
        "api_create_connector",
    }
    assert names <= set(executive_by_name)
    assert names <= set(worker_by_name)
    assert all(executive_by_name[name]["assigned"] for name in names)
    assert all(not worker_by_name[name]["assigned"] for name in names)
