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
            "name": "Executive " + suffix,
            "provider_id": "lmstudio",
            "default_model": "executive-model",
        },
    )
    assert connection.status_code == 201

    project = client.post(
        "/api/projects",
        json={
            "name": "Executive Project " + suffix,
            "workspace_path": "D:\\AgentMan\\executive-tests\\" + suffix,
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
            "model": "executive-model",
            "temperature": 0.2,
        },
    )
    assert configured.status_code == 200
    return project.json(), workers


def test_main_agent_delegates_and_returns_unified_answer(monkeypatch):
    project, workers = _setup()
    calls = {"count": 0}

    def fake_run_messages(agent, messages, endpoint=None):
        calls["count"] += 1
        if calls["count"] == 1:
            return json.dumps({
                "type": "delegate_agent",
                "agent_id": workers["Developer"]["id"],
                "task": "Implement the requested feature and verify it.",
            })
        return json.dumps({
            "type": "reply",
            "message": "I delegated implementation to Developer, reviewed the result, and the feature is complete.",
        })

    def fake_execute_agent(**kwargs):
        assert kwargs["agent"].id == workers["Developer"]["id"]
        return {
            "status": "completed",
            "text": "Feature implemented. Tests passed.",
            "steps": [{"tool": "run_tests", "status": "ok"}],
        }

    monkeypatch.setattr(
        "app.agents.executive.run_messages",
        fake_run_messages,
    )
    monkeypatch.setattr(
        "app.agents.executive.execute_agent",
        fake_execute_agent,
    )

    response = client.post(
        "/api/main-agent/projects/" + project["id"] + "/chat",
        json={
            "message": "Build the feature and make sure it works.",
            "allow_terminal": True,
            "allow_delete": False,
            "allow_network": False,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert "Developer" in body["text"]
    assert len(body["steps"]) == 1
    assert body["steps"][0]["type"] == "delegate_agent"

    messages = client.get(
        "/api/main-agent/projects/" + project["id"] + "/messages"
    )
    assert messages.status_code == 200
    assert [item["role"] for item in messages.json()][-2:] == [
        "user",
        "assistant",
    ]


def test_main_agent_can_reply_without_delegating(monkeypatch):
    project, _workers = _setup()

    monkeypatch.setattr(
        "app.agents.executive.run_messages",
        lambda agent, messages, endpoint=None: json.dumps({
            "type": "reply",
            "message": "All systems are available.",
        }),
    )

    response = client.post(
        "/api/main-agent/projects/" + project["id"] + "/chat",
        json={
            "message": "What can you do?",
            "allow_terminal": False,
            "allow_delete": False,
            "allow_network": False,
        },
    )
    assert response.status_code == 200
    assert response.json()["text"] == "All systems are available."
    assert response.json()["steps"] == []



def test_main_agent_can_use_runtime_tools_directly(monkeypatch):
    project, _workers = _setup()
    calls = {"count": 0, "allowed": set()}

    def fake_run_messages(agent, messages, endpoint=None):
        calls["count"] += 1
        if calls["count"] == 1:
            return json.dumps({
                "type": "tool",
                "tool": "read_file",
                "args": {"path": "README.md"},
            })
        return json.dumps({
            "type": "reply",
            "message": "I inspected the project directly with my runtime tools.",
        })

    def fake_execute(**kwargs):
        calls["allowed"] = set(kwargs["allowed_names"])
        assert kwargs["name"] == "read_file"
        assert kwargs["workspace_path"] == project["workspace_path"]
        return {"path": "README.md", "content": "Agent Man"}

    monkeypatch.setattr(
        "app.agents.executive.run_messages",
        fake_run_messages,
    )
    monkeypatch.setattr(
        "app.agents.executive.tools.execute",
        fake_execute,
    )

    response = client.post(
        "/api/main-agent/projects/" + project["id"] + "/chat",
        json={
            "message": "Inspect README yourself.",
            "allow_terminal": False,
            "allow_delete": False,
            "allow_network": False,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["steps"][0]["type"] == "tool"
    assert body["steps"][0]["tool"] == "read_file"
    assert body["steps"][0]["status"] == "ok"
    assert "read_file" in calls["allowed"]
    assert "run_tests" in calls["allowed"]
    assert "http_get" in calls["allowed"]


def test_main_agent_direct_tool_respects_approval(monkeypatch):
    project, _workers = _setup()

    monkeypatch.setattr(
        "app.agents.executive.run_messages",
        lambda agent, messages, endpoint=None: json.dumps({
            "type": "tool",
            "tool": "run_command",
            "args": {"command": "echo hello"},
        }),
    )

    response = client.post(
        "/api/main-agent/projects/" + project["id"] + "/chat",
        json={
            "message": "Run the command yourself.",
            "allow_terminal": False,
            "allow_delete": False,
            "allow_network": False,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "waiting_approval"
    assert body["steps"][0]["permission"] == "terminal.execute"



def test_main_agent_tool_assignment_can_be_changed(monkeypatch):
    project, _workers = _setup()

    listed = client.get(
        "/api/tools/main-agent/" + project["id"]
    )
    assert listed.status_code == 200
    assert any(
        item["name"] == "read_file" and item["assigned"]
        for item in listed.json()
    )

    changed = client.put(
        "/api/tools/main-agent/"
        + project["id"]
        + "/read_file",
        json={"enabled": False},
    )
    assert changed.status_code == 200
    assert changed.json()["assigned"] is False

    calls = {"count": 0}

    def fake_run_messages(agent, messages, endpoint=None):
        calls["count"] += 1
        if calls["count"] == 1:
            assert "read_file" not in messages[0]["content"]
            return json.dumps({
                "type": "tool",
                "tool": "read_file",
                "args": {"path": "README.md"},
            })
        return json.dumps({
            "type": "reply",
            "message": "The requested tool is not assigned to me.",
        })

    monkeypatch.setattr(
        "app.agents.executive.run_messages",
        fake_run_messages,
    )

    response = client.post(
        "/api/main-agent/projects/" + project["id"] + "/chat",
        json={
            "message": "Read README.",
            "allow_terminal": False,
            "allow_delete": False,
            "allow_network": False,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["steps"][0]["type"] == "tool"
    assert body["steps"][0]["status"] == "error"
    assert "disabled or not assigned" in body["steps"][0]["error"]



def test_worker_state_moves_through_working_verifying_completed(monkeypatch):
    project, workers = _setup()
    developer = workers["Developer"]
    calls = {"count": 0}

    def fake_run_messages(agent, messages, endpoint=None):
        calls["count"] += 1
        if calls["count"] == 1:
            assert agent.state == "working"
            return json.dumps({
                "type": "final",
                "verified": True,
                "message": "Implementation candidate complete.",
            })

        assert agent.state == "verifying"
        return json.dumps({
            "type": "final",
            "verified": True,
            "message": "Implementation verified complete.",
        })

    monkeypatch.setattr(
        "app.agents.executor.run_messages",
        fake_run_messages,
    )

    response = client.post(
        "/api/agents/" + developer["id"] + "/execute",
        json={
            "prompt": "Complete and verify the implementation.",
            "allow_terminal": False,
            "allow_delete": False,
            "allow_network": False,
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "completed"

    listed = client.get(
        "/api/projects/" + project["id"] + "/agents"
    )
    assert listed.status_code == 200
    saved = next(
        item
        for item in listed.json()
        if item["id"] == developer["id"]
    )
    assert saved["state"] == "completed"


def test_tester_enters_validating_state(monkeypatch):
    project, workers = _setup()
    tester = workers["Tester"]
    calls = {"count": 0}

    def fake_run_messages(agent, messages, endpoint=None):
        calls["count"] += 1
        if calls["count"] == 1:
            assert agent.state == "validating"
        return json.dumps({
            "type": "final",
            "verified": True,
            "message": "Validation complete.",
        })

    monkeypatch.setattr(
        "app.agents.executor.run_messages",
        fake_run_messages,
    )

    response = client.post(
        "/api/agents/" + tester["id"] + "/execute",
        json={
            "prompt": "Validate the implementation.",
            "allow_terminal": False,
            "allow_delete": False,
            "allow_network": False,
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "completed"



def test_main_agent_bulk_tool_access_controls():
    project, _workers = _setup()

    revoked = client.put(
        "/api/tools/main-agent/"
        + project["id"]
        + "/bulk/revoke-all"
    )
    assert revoked.status_code == 200

    listed = client.get(
        "/api/tools/main-agent/" + project["id"]
    )
    assert listed.status_code == 200
    assert all(
        not item["assigned"]
        for item in listed.json()
    )

    granted = client.put(
        "/api/tools/main-agent/"
        + project["id"]
        + "/bulk/grant-all"
    )
    assert granted.status_code == 200
    assert granted.json()["updated"] > 0

    listed_again = client.get(
        "/api/tools/main-agent/" + project["id"]
    )
    assert listed_again.status_code == 200
    enabled = [
        item
        for item in listed_again.json()
        if item["globally_enabled"]
    ]
    assert enabled
    assert all(item["assigned"] for item in enabled)



def test_main_agent_serial_tool_requires_hardware_approval(monkeypatch):
    project, _workers = _setup()

    monkeypatch.setattr(
        "app.agents.executive.run_messages",
        lambda agent, messages, endpoint=None: json.dumps({
            "type": "tool",
            "tool": "serial_open",
            "args": {
                "device": "COM3",
                "baudrate": 115200,
            },
        }),
    )

    response = client.post(
        "/api/main-agent/projects/" + project["id"] + "/chat",
        json={
            "message": "Open the ESP32 serial port.",
            "allow_terminal": False,
            "allow_delete": False,
            "allow_network": False,
            "allow_hardware": False,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "waiting_approval"
    assert body["steps"][0]["tool"] == "serial_open"
    assert body["steps"][0]["permission"] == "hardware.serial"
