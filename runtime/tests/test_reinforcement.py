import json
from uuid import uuid4

from fastapi.testclient import TestClient

from app.agents.background_jobs import background_jobs
from app.main import app

client = TestClient(app)


def _setup():
    suffix = str(uuid4())[:8]
    connection = client.post(
        "/api/ai/connections",
        json={
            "name": "RL " + suffix,
            "provider_id": "lmstudio",
            "default_model": "rl-model",
        },
    )
    assert connection.status_code == 201

    project = client.post(
        "/api/projects",
        json={
            "name": "RL Project " + suffix,
            "workspace_path": "D:\\AgentMan\\rl-tests\\" + suffix,
        },
    )
    assert project.status_code == 201

    agent = client.post(
        "/api/agents",
        json={
            "project_id": project.json()["id"],
            "name": "Developer " + suffix,
            "role": "Developer",
            "context": "Implement and verify changes.",
            "llm": {
                "provider_id": "lmstudio",
                "connection_id": connection.json()["id"],
                "model": "developer-model",
            },
        },
    )
    assert agent.status_code == 201

    configured = client.put(
        "/api/main-agent/projects/"
        + project.json()["id"]
        + "/config",
        json={
            "connection_id": connection.json()["id"],
            "model": "rl-model",
            "temperature": 0.2,
        },
    )
    assert configured.status_code == 200

    return project.json(), agent.json()


def test_user_feedback_persists_and_updates_reward_summary():
    project, agent = _setup()

    positive = client.post(
        "/api/main-agent/projects/"
        + project["id"]
        + "/reinforcement/feedback",
        json={
            "value": 1,
            "agent_id": agent["id"],
            "agent_name": agent["name"],
            "task": "Implement a dashboard fix.",
            "note": "Worked well.",
        },
    )
    assert positive.status_code == 200
    assert positive.json()["outcome"] == "user_positive"
    assert positive.json()["reward"] == 1.0

    negative = client.post(
        "/api/main-agent/projects/"
        + project["id"]
        + "/reinforcement/feedback",
        json={
            "value": -1,
            "agent_id": agent["id"],
            "agent_name": agent["name"],
            "task": "Implement another fix.",
            "note": "Wrong approach.",
        },
    )
    assert negative.status_code == 200
    assert negative.json()["outcome"] == "user_negative"
    assert negative.json()["reward"] == -1.0

    summary = client.get(
        "/api/main-agent/projects/"
        + project["id"]
        + "/reinforcement/summary"
    )
    assert summary.status_code == 200
    body = summary.json()
    assert body["events"] == 2
    assert body["overall"]["count"] == 2
    assert body["overall"]["average_reward"] == 0.0

    score = next(
        item
        for item in body["agents"]
        if item["agent_id"] == agent["id"]
    )
    assert score["count"] == 2
    assert score["positive"] == 1
    assert score["negative"] == 1


def test_background_completion_records_automatic_agent_reward(monkeypatch):
    project, agent = _setup()

    def fake_execute_agent(**kwargs):
        return {
            "status": "completed",
            "text": "Implemented and verified.",
            "steps": [
                {
                    "turn": 1,
                    "tool": "read_file",
                    "status": "ok",
                },
                {
                    "turn": 2,
                    "tool": "run_tests",
                    "status": "ok",
                },
            ],
        }

    monkeypatch.setattr(
        "app.agents.background_jobs.execute_agent",
        fake_execute_agent,
    )

    job = background_jobs.start_agent(
        project_id=project["id"],
        agent_id=agent["id"],
        agent_name=agent["name"],
        agent_role=agent["role"],
        task="Implement and verify the feature.",
    )
    finished = background_jobs.wait(job["id"], timeout=5)
    assert finished["status"] == "completed"

    summary = client.get(
        "/api/main-agent/projects/"
        + project["id"]
        + "/reinforcement/summary"
    )
    assert summary.status_code == 200
    body = summary.json()
    score = next(
        item
        for item in body["agents"]
        if item["agent_id"] == agent["id"]
    )
    assert score["count"] >= 1
    assert score["average_reward"] > 0


def test_executive_receives_reinforcement_policy_memory(monkeypatch):
    project, agent = _setup()

    feedback = client.post(
        "/api/main-agent/projects/"
        + project["id"]
        + "/reinforcement/feedback",
        json={
            "value": 1,
            "agent_id": agent["id"],
            "agent_name": agent["name"],
            "task": "Implement React work.",
            "note": "Good result.",
        },
    )
    assert feedback.status_code == 200

    captured = {}

    def respond(agent_proxy, messages, endpoint=None):
        captured["system"] = messages[0]["content"]
        return json.dumps({
            "type": "reply",
            "message": "I am ready.",
        })

    monkeypatch.setattr(
        "app.agents.executive.run_messages",
        respond,
    )

    response = client.post(
        "/api/main-agent/projects/"
        + project["id"]
        + "/chat",
        json={"message": "What should we work on next?"},
    )
    assert response.status_code == 200
    system = captured["system"]
    assert "REINFORCEMENT POLICY MEMORY:" in system
    assert agent["name"] in system
    assert "avg=1.0" in system
    assert "never override permissions" in system.lower()
