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
            "name": "Workflow " + suffix,
            "provider_id": "lmstudio",
            "default_model": "test-model",
        },
    )
    assert connection.status_code == 201

    project = client.post(
        "/api/projects",
        json={
            "name": "Workflow Project " + suffix,
            "workspace_path": "D:\\AgentMan\\workflow-tests\\" + suffix,
        },
    )
    assert project.status_code == 201

    agents = {}
    for role in ["Architect", "Developer", "Tester"]:
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
        agents[role] = response.json()

    return project.json(), agents


def test_orchestration_follows_success_edges(monkeypatch):
    project, agents = _setup()

    def fake_run_messages(agent, messages, endpoint=None):
        return json.dumps(
            {
                "type": "final",
                "outcome": "success",
                "message": agent.role + " stage completed.",
            }
        )

    monkeypatch.setattr(
        "app.agents.orchestration.run_messages",
        fake_run_messages,
    )

    workflow = client.post(
        "/api/orchestration/workflows",
        json={
            "project_id": project["id"],
            "name": "Architect Developer Tester",
            "description": "Sequential success path",
            "nodes": [
                {
                    "key": "architect",
                    "name": "Architecture",
                    "agent_id": agents["Architect"]["id"],
                    "instructions": "Create the plan.",
                    "on_success_key": "developer",
                    "on_failure_key": None,
                    "max_retries": 0,
                },
                {
                    "key": "developer",
                    "name": "Implementation",
                    "agent_id": agents["Developer"]["id"],
                    "instructions": "Implement the plan.",
                    "on_success_key": "tester",
                    "on_failure_key": None,
                    "max_retries": 0,
                },
                {
                    "key": "tester",
                    "name": "Validation",
                    "agent_id": agents["Tester"]["id"],
                    "instructions": "Validate acceptance criteria.",
                    "on_success_key": None,
                    "on_failure_key": "developer",
                    "max_retries": 0,
                },
            ],
        },
    )
    assert workflow.status_code == 201

    run = client.post(
        "/api/orchestration/workflows/"
        + workflow.json()["id"]
        + "/runs",
        json={
            "input_prompt": "Build and validate the requested feature.",
            "allow_terminal": False,
            "allow_delete": False,
        },
    )
    assert run.status_code == 201
    body = run.json()
    assert body["status"] == "completed"
    assert [step["node_name"] for step in body["steps"]] == [
        "Architecture",
        "Implementation",
        "Validation",
    ]
    assert all(step["outcome"] == "success" for step in body["steps"])


def test_orchestration_follows_failure_edge(monkeypatch):
    project, agents = _setup()
    developer_visits = {"count": 0}

    def fake_run_messages(agent, messages, endpoint=None):
        if agent.role == "Architect":
            outcome = "success"
        elif agent.role == "Developer":
            developer_visits["count"] += 1
            outcome = "success"
        else:
            outcome = "failure"
        return json.dumps(
            {
                "type": "final",
                "outcome": outcome,
                "message": agent.role + " returned " + outcome,
            }
        )

    monkeypatch.setattr(
        "app.agents.orchestration.run_messages",
        fake_run_messages,
    )

    workflow = client.post(
        "/api/orchestration/workflows",
        json={
            "project_id": project["id"],
            "name": "Failure routing",
            "description": "Tester failure routes back to developer.",
            "nodes": [
                {
                    "key": "architect",
                    "name": "Architecture",
                    "agent_id": agents["Architect"]["id"],
                    "instructions": "Plan.",
                    "on_success_key": "developer",
                    "on_failure_key": None,
                    "max_retries": 0,
                },
                {
                    "key": "developer",
                    "name": "Developer",
                    "agent_id": agents["Developer"]["id"],
                    "instructions": "Implement.",
                    "on_success_key": "tester",
                    "on_failure_key": None,
                    "max_retries": 0,
                },
                {
                    "key": "tester",
                    "name": "Tester",
                    "agent_id": agents["Tester"]["id"],
                    "instructions": "Test.",
                    "on_success_key": None,
                    "on_failure_key": "developer",
                    "max_retries": 0,
                },
            ],
        },
    )
    assert workflow.status_code == 201

    run = client.post(
        "/api/orchestration/workflows/"
        + workflow.json()["id"]
        + "/runs",
        json={
            "input_prompt": "Exercise the retry loop.",
            "allow_terminal": False,
            "allow_delete": False,
        },
    )
    assert run.status_code == 201
    assert run.json()["status"] == "transition_limit"
    assert developer_visits["count"] > 1
