import json
from threading import Event
from time import sleep, time
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.persistence.database import SessionLocal
from app.persistence.models import (
    MultiAgentMessageRecord,
    MultiAgentTaskRecord,
)


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


def _create_room(project, workers):
    created = client.post(
        "/api/meeting-rooms",
        json={
            "project_id": project["id"],
            "title": "Implementation Room",
            "objective": "Solve the issue collaboratively.",
            "agent_ids": [
                workers["Developer"]["id"],
                workers["Tester"]["id"],
            ],
        },
    )
    assert created.status_code == 201
    return created.json()


def _wait_for_room_message(
    room_id: str,
    kind: str,
    timeout: float = 2.0,
):
    deadline = time() + timeout
    latest = None
    while time() < deadline:
        response = client.get("/api/meeting-rooms/" + room_id)
        assert response.status_code == 200
        latest = response.json()
        if any(
            message["kind"] == kind
            for message in latest["messages"]
        ):
            return latest
        sleep(0.02)
    raise AssertionError(
        "Room message kind "
        + repr(kind)
        + " did not appear; latest="
        + repr(latest)
    )


def _wait_for_collaboration(
    room_id: str,
    statuses: set[str],
    timeout: float = 3.0,
):
    deadline = time() + timeout
    latest = None
    while time() < deadline:
        response = client.get("/api/meeting-rooms/" + room_id)
        assert response.status_code == 200
        latest = response.json()
        if (
            latest["collaborations"]
            and latest["collaborations"][0]["status"] in statuses
        ):
            return latest
        sleep(0.02)
    raise AssertionError(
        "Collaboration did not reach "
        + repr(statuses)
        + "; latest="
        + repr(latest)
    )


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

    def respond(agent, messages, endpoint=None):
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
    created_step = next(
        step
        for step in body["steps"]
        if step["type"] == "create_meeting_room"
    )
    assert set(created_step["agent_ids"]) == {
        workers["Developer"]["id"],
        ui_designer["id"],
    }


def test_room_instruction_runs_all_peers_until_stable_completion(monkeypatch):
    project, workers = _setup()
    room = _create_room(project, workers)

    def fake_peer_turn(**kwargs):
        round_number = kwargs["round_number"]
        agent = kwargs["agent"]
        if round_number < 14:
            return {
                "type": "message",
                "content": (
                    agent.name
                    + " is still collaborating in round "
                    + str(round_number)
                ),
                "tool_steps": 0,
            }
        return {
            "type": "final",
            "content": agent.name + " confirms the shared task is complete.",
            "tool_steps": 0,
        }

    monkeypatch.setattr(
        "app.agents.multi_agent._run_peer_turn",
        fake_peer_turn,
    )

    instructed = client.post(
        "/api/meeting-rooms/" + room["id"] + "/instructions",
        json={"instruction": "Fix and verify the portfolio issue."},
    )
    assert instructed.status_code == 200
    assert instructed.json()["collaborations"]

    completed = _wait_for_collaboration(
        room["id"],
        {"completed", "completed_with_errors"},
        timeout=4.0,
    )
    collaboration = completed["collaborations"][0]

    # Room sessions are continuous: this deliberately exceeds the normal
    # 12-round ceiling and still runs until stable peer completion.
    assert collaboration["current_round"] >= 15
    assert {
        participant["agent_id"]
        for participant in collaboration["participants"]
    } == {
        workers["Developer"]["id"],
        workers["Tester"]["id"],
    }
    assert all(
        participant["status"] == "completed"
        for participant in collaboration["participants"]
    )
    assert any(
        message["kind"] == "peer_message"
        for message in completed["messages"]
    )
    assert any(
        message["kind"] == "peer_final"
        for message in completed["messages"]
    )
    completed = _wait_for_room_message(
        room["id"],
        "collaboration_completed",
    )
    assert any(
        message["kind"] == "collaboration_completed"
        for message in completed["messages"]
    )


def test_followup_instruction_joins_live_room_and_agent_can_be_kicked(
    monkeypatch,
):
    project, workers = _setup()
    room = _create_room(project, workers)

    monkeypatch.setattr(
        "app.agents.room_collaboration.room_collaborations.start",
        lambda *args, **kwargs: None,
    )

    first = client.post(
        "/api/meeting-rooms/" + room["id"] + "/instructions",
        json={"instruction": "Start investigating the portfolio bug."},
    )
    assert first.status_code == 200
    task_id = first.json()["collaborations"][0]["id"]

    followup = client.post(
        "/api/meeting-rooms/" + room["id"] + "/instructions",
        json={"instruction": "Also verify the mobile layout."},
    )
    assert followup.status_code == 200
    assert len(followup.json()["collaborations"]) == 1

    with SessionLocal() as db:
        task = db.get(MultiAgentTaskRecord, task_id)
        assert task is not None
        followup_message = db.scalar(
            select(MultiAgentMessageRecord).where(
                MultiAgentMessageRecord.task_id == task_id,
                MultiAgentMessageRecord.kind == "user_instruction",
            )
        )
        assert followup_message is not None
        assert "mobile layout" in followup_message.content

    kicked = client.post(
        "/api/meeting-rooms/"
        + room["id"]
        + "/members/"
        + workers["Tester"]["id"]
        + "/kick"
    )
    assert kicked.status_code == 200
    body = kicked.json()
    tester = next(
        member
        for member in body["members"]
        if member["agent_id"] == workers["Tester"]["id"]
    )
    assert tester["active"] is False
    participant = next(
        item
        for item in body["collaborations"][0]["participants"]
        if item["agent_id"] == workers["Tester"]["id"]
    )
    assert participant["status"] == "kicked"
    assert any(
        message["kind"] == "agent_kicked"
        for message in body["messages"]
    )


def test_room_cannot_close_until_shared_collaboration_stops(monkeypatch):
    project, workers = _setup()
    room = _create_room(project, workers)
    entered_turn = Event()
    release_turn = Event()

    def blocking_peer_turn(**kwargs):
        entered_turn.set()
        release_turn.wait(timeout=2.0)
        return {
            "type": "message",
            "content": "Continuing shared work.",
            "tool_steps": 0,
        }

    monkeypatch.setattr(
        "app.agents.multi_agent._run_peer_turn",
        blocking_peer_turn,
    )

    instructed = client.post(
        "/api/meeting-rooms/" + room["id"] + "/instructions",
        json={"instruction": "Keep working until this is resolved."},
    )
    assert instructed.status_code == 200
    task_id = instructed.json()["collaborations"][0]["id"]
    assert entered_turn.wait(timeout=1.0)

    close = client.post(
        "/api/meeting-rooms/" + room["id"] + "/close"
    )
    assert close.status_code == 409

    stop = client.post(
        "/api/meeting-rooms/"
        + room["id"]
        + "/collaborations/"
        + task_id
        + "/stop"
    )
    assert stop.status_code == 200
    release_turn.set()

    stopped = _wait_for_collaboration(
        room["id"],
        {"stopped"},
        timeout=3.0,
    )
    assert stopped["collaborations"][0]["status"] == "stopped"

    closed = client.post(
        "/api/meeting-rooms/" + room["id"] + "/close"
    )
    assert closed.status_code == 200
    assert closed.json()["status"] == "closed"
