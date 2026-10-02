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
            "name": "History " + suffix,
            "provider_id": "lmstudio",
            "default_model": "history-model",
        },
    )
    assert connection.status_code == 201

    project = client.post(
        "/api/projects",
        json={
            "name": "History Project " + suffix,
            "workspace_path": "D:\\AgentMan\\history-tests\\" + suffix,
        },
    )
    assert project.status_code == 201

    agent = client.post(
        "/api/agents",
        json={
            "project_id": project.json()["id"],
            "name": "Developer " + suffix,
            "role": "Developer",
            "context": "Implement and verify assigned changes.",
            "llm": {
                "provider_id": "lmstudio",
                "connection_id": connection.json()["id"],
                "model": "history-model",
            },
        },
    )
    assert agent.status_code == 201

    return project.json(), agent.json()


def test_completed_background_job_is_persisted_in_agent_task_history(monkeypatch):
    project, agent = _setup()

    monkeypatch.setattr(
        "app.agents.background_jobs.execute_agent",
        lambda **kwargs: {
            "status": "completed",
            "text": "Implemented the navbar fix and verified the build.",
            "steps": [
                {
                    "turn": 1,
                    "tool": "read_file",
                    "status": "ok",
                },
                {
                    "turn": 2,
                    "tool": "run_build",
                    "status": "ok",
                },
            ],
        },
    )

    job = background_jobs.start_agent(
        project_id=project["id"],
        agent_id=agent["id"],
        agent_name=agent["name"],
        agent_role=agent["role"],
        task="Fix the navbar alignment.",
    )
    finished = background_jobs.wait(job["id"], timeout=5)
    assert finished["status"] == "completed"

    response = client.get(
        "/api/main-agent/projects/"
        + project["id"]
        + "/task-history"
    )
    assert response.status_code == 200
    rows = response.json()
    item = next(row for row in rows if row["id"] == job["id"])

    assert item["agent_id"] == agent["id"]
    assert item["agent_name"] == agent["name"]
    assert item["agent_role"] == agent["role"]
    assert item["task"] == "Fix the navbar alignment."
    assert item["status"] == "completed"
    assert item["step_count"] == 2
    assert "navbar fix" in item["result_text"]
    assert item["started_at"] is not None
    assert item["completed_at"] is not None


def test_approval_resume_updates_same_persistent_task_history_row(monkeypatch):
    project, agent = _setup()
    calls = {"count": 0}

    def fake_execute_agent(**kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return {
                "status": "waiting_approval",
                "text": "Delete approval required.",
                "steps": [
                    {
                        "turn": 1,
                        "tool": "delete_path",
                        "status": "approval_required",
                        "permission": "project.files.delete",
                    }
                ],
            }
        return {
            "status": "completed",
            "text": "Obsolete file removed and verified.",
            "steps": [
                {
                    "turn": 1,
                    "tool": "delete_path",
                    "status": "ok",
                }
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
        task="Remove the obsolete generated file.",
    )
    waiting = background_jobs.wait(job["id"], timeout=5)
    assert waiting["status"] == "waiting_approval"

    waiting_history = client.get(
        "/api/main-agent/projects/"
        + project["id"]
        + "/task-history"
    )
    assert waiting_history.status_code == 200
    waiting_item = next(
        row
        for row in waiting_history.json()
        if row["id"] == job["id"]
    )
    assert waiting_item["status"] == "waiting_approval"

    approved = client.post(
        "/api/main-agent/projects/"
        + project["id"]
        + "/background-jobs/"
        + job["id"]
        + "/approve"
    )
    assert approved.status_code == 200
    assert approved.json()["id"] == job["id"]

    finished = background_jobs.wait(job["id"], timeout=5)
    assert finished["status"] == "completed"

    response = client.get(
        "/api/main-agent/projects/"
        + project["id"]
        + "/task-history"
    )
    assert response.status_code == 200
    rows = [row for row in response.json() if row["id"] == job["id"]]
    assert len(rows) == 1
    item = rows[0]
    assert item["status"] == "completed"
    assert item["task"] == "Remove the obsolete generated file."
    assert "Obsolete file removed" in item["result_text"]
    assert item["completed_at"] is not None


def test_background_page_exposes_agent_work_history_ui():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    page = (
        root
        / "apps"
        / "web"
        / "src"
        / "features"
        / "agents"
        / "BackgroundPage.tsx"
    ).read_text(encoding="utf-8")

    assert "Agent work history" in page
    assert "api.taskHistory(project.id)" in page
    assert "All agents" in page
    assert "All statuses" in page
    assert "Persistent record of which agent worked on each delegated task." in page
