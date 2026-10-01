import json
from threading import Event
from time import sleep
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
            "name": "Meeting Rooms " + suffix,
            "provider_id": "lmstudio",
            "default_model": "meeting-model",
        },
    )
    assert connection.status_code == 201

    project = client.post(
        "/api/projects",
        json={
            "name": "Meeting Project " + suffix,
            "workspace_path": "D:\\AgentMan\\meeting-tests\\" + suffix,
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
                "context": (
                    "Implement product changes and validate them."
                    if role == "Developer"
                    else "Test changes and report regressions."
                ),
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
            "model": "meeting-model",
            "temperature": 0.2,
        },
    )
    assert configured.status_code == 200

    return project.json(), workers


def test_executive_can_create_persistent_meeting_room(monkeypatch):
    project, workers = _setup()
    developer = workers["Developer"]
    captured = {"calls": 0}

    def respond(agent, messages, endpoint=None):
        captured["calls"] += 1
        return json.dumps(
            {
                "type": "create_meeting_room",
                "title": "Login Fix",
                "objective": "Fix and validate the login problem.",
                "agent_ids": [developer["id"]],
            }
        )

    monkeypatch.setattr(
        "app.agents.executive.run_messages",
        respond,
    )

    response = client.post(
        "/api/main-agent/projects/" + project["id"] + "/chat",
        json={
            "message": (
                "Create a meeting room for the login issue and connect "
                "the relevant agent."
            )
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "meeting_room"
    assert body["steps"][0]["type"] == "create_meeting_room"
    assert captured["calls"] == 1

    rooms = client.get(
        "/api/meeting-rooms/projects/" + project["id"]
    )
    assert rooms.status_code == 200
    assert len(rooms.json()) == 1

    room = rooms.json()[0]
    assert room["title"] == "Login Fix"
    assert room["executive"]["name"] == "Agent Man"
    assert room["executive"]["role"] == "Executive"
    assert [item["agent_id"] for item in room["members"]] == [
        developer["id"]
    ]
    assert room["messages"][0]["kind"] == "room_created"


def test_executive_resolves_placeholder_worker_ids_to_real_workers(monkeypatch):
    project, workers = _setup()
    suffix = workers["Developer"]["name"].removeprefix("Developer ")

    designer = client.post(
        "/api/agents",
        json={
            "project_id": project["id"],
            "name": "UI Designer " + suffix,
            "role": "UI Designer",
            "context": "Design and refine the portfolio user interface.",
            "llm": {
                "provider_id": "lmstudio",
                "connection_id": workers["Developer"]["llm"]["connection_id"],
                "model": "ui-designer-model",
            },
        },
    )
    assert designer.status_code == 201
    ui_designer = designer.json()
    calls = {"count": 0}

    def respond(agent, messages, endpoint=None):
        calls["count"] += 1
        return json.dumps(
            {
                "type": "create_meeting_room",
                "title": "Portfolio Issues",
                "objective": "Discuss and resolve portfolio-related issues",
                "agent_ids": ["developer-id", "ui-designer-id"],
            }
        )

    monkeypatch.setattr(
        "app.agents.executive.run_messages",
        respond,
    )

    response = client.post(
        "/api/main-agent/projects/" + project["id"] + "/chat",
        json={
            "message": (
                "Create a meeting room for portfolio issues with the "
                "Developer and UI Designer."
            )
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "meeting_room"
    assert calls["count"] == 1

    created_step = next(
        step
        for step in body["steps"]
        if step["type"] == "create_meeting_room"
    )
    assert set(created_step["agent_ids"]) == {
        workers["Developer"]["id"],
        ui_designer["id"],
    }

    room = client.get(
        "/api/meeting-rooms/" + created_step["room_id"]
    )
    assert room.status_code == 200
    assert {
        member["agent_id"]
        for member in room.json()["members"]
    } == {
        workers["Developer"]["id"],
        ui_designer["id"],
    }


def test_room_instruction_tracks_background_job_and_manual_stop(monkeypatch):
    project, workers = _setup()
    developer = workers["Developer"]

    created = client.post(
        "/api/meeting-rooms",
        json={
            "project_id": project["id"],
            "title": "Implementation Room",
            "objective": "Implement one scoped change.",
            "agent_ids": [developer["id"]],
        },
    )
    assert created.status_code == 201
    room_id = created.json()["id"]

    worker_started = Event()

    def fake_execute_agent(
        *,
        agent,
        project,
        prompt,
        db,
        endpoint=None,
        allow_terminal=False,
        allow_delete=False,
        allow_network=False,
        allow_hardware=False,
        progress=None,
        should_stop=None,
    ):
        worker_started.set()
        if progress:
            progress(
                {
                    "phase": "working",
                    "action": "Editing the requested feature.",
                    "tool": "edit_file",
                    "detail": "Working in the project sandbox.",
                    "next_step": "Run the focused tests.",
                    "status": "running",
                }
            )

        for _ in range(200):
            if should_stop and should_stop():
                return {
                    "status": "stopped",
                    "text": "Stopped by the user.",
                    "steps": [],
                }
            sleep(0.01)

        return {
            "status": "completed",
            "text": "Finished.",
            "steps": [],
        }

    monkeypatch.setattr(
        "app.agents.background_jobs.execute_agent",
        fake_execute_agent,
    )

    instructed = client.post(
        "/api/meeting-rooms/" + room_id + "/instructions",
        json={
            "agent_id": developer["id"],
            "instruction": "Implement the login button fix.",
        },
    )
    assert instructed.status_code == 200
    body = instructed.json()
    assert body["jobs"]
    job = body["jobs"][0]
    assert job["room_id"] == room_id
    assert job["agent_id"] == developer["id"]
    assert worker_started.wait(timeout=1.0)

    stop = client.post(
        "/api/main-agent/projects/"
        + project["id"]
        + "/background-jobs/"
        + job["id"]
        + "/stop"
    )
    assert stop.status_code == 200
    assert stop.json()["status"] in {"stopping", "stopped"}

    final_job = background_jobs.wait(job["id"], timeout=3.0)
    assert final_job is not None
    assert final_job["status"] == "stopped"
    assert final_job["room_id"] == room_id
    assert final_job["current_action"] == "Stopped by the user."

    fresh = client.get("/api/meeting-rooms/" + room_id)
    assert fresh.status_code == 200
    room = fresh.json()
    assert any(
        message["kind"] == "instruction"
        and "login button" in message["content"]
        for message in room["messages"]
    )
    assert any(
        message["kind"] == "assignment"
        and message["job_id"] == job["id"]
        for message in room["messages"]
    )
    assert any(
        message["kind"] == "task_stopped"
        and message["job_id"] == job["id"]
        for message in room["messages"]
    )

    history = client.get(
        "/api/main-agent/projects/" + project["id"] + "/task-history"
    )
    assert history.status_code == 200
    row = next(
        item
        for item in history.json()
        if item["id"] == job["id"]
    )
    assert row["room_id"] == room_id
    assert row["status"] == "stopped"


def test_room_cannot_close_while_worker_is_active(monkeypatch):
    project, workers = _setup()
    developer = workers["Developer"]

    created = client.post(
        "/api/meeting-rooms",
        json={
            "project_id": project["id"],
            "title": "Active Room",
            "objective": "Keep task visible until stopped.",
            "agent_ids": [developer["id"]],
        },
    )
    assert created.status_code == 201
    room_id = created.json()["id"]

    release = Event()

    def fake_execute_agent(**kwargs):
        should_stop = kwargs.get("should_stop")
        for _ in range(200):
            if release.is_set():
                break
            if should_stop and should_stop():
                return {
                    "status": "stopped",
                    "text": "Stopped by the user.",
                    "steps": [],
                }
            sleep(0.01)
        return {
            "status": "completed",
            "text": "Done.",
            "steps": [],
        }

    monkeypatch.setattr(
        "app.agents.background_jobs.execute_agent",
        fake_execute_agent,
    )

    instructed = client.post(
        "/api/meeting-rooms/" + room_id + "/instructions",
        json={
            "agent_id": developer["id"],
            "instruction": "Work on the task.",
        },
    )
    assert instructed.status_code == 200
    job = instructed.json()["jobs"][0]

    close = client.post(
        "/api/meeting-rooms/" + room_id + "/close"
    )
    assert close.status_code == 409

    client.post(
        "/api/main-agent/projects/"
        + project["id"]
        + "/background-jobs/"
        + job["id"]
        + "/stop"
    )
    background_jobs.wait(job["id"], timeout=3.0)
    release.set()

    closed = client.post(
        "/api/meeting-rooms/" + room_id + "/close"
    )
    assert closed.status_code == 200
    assert closed.json()["status"] == "closed"
