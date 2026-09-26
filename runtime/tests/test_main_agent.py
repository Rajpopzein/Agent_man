import json
import pytest
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_native_serial_template_executes_and_returns_context(monkeypatch):
    project, _ = _setup()
    discoveries = []

    def ports():
        discoveries.append(True)
        return [{"device": "COM7", "manufacturer": "Espressif"}]

    answers = iter([
        r'<|tool\_call>call:list\_serial\_ports{}\<tool\_call|>',
        '{"type":"reply","message":"An Espressif device is detected on COM7. Serial communication is not yet verified."}',
    ])
    monkeypatch.setattr("app.tools.registry.serial_devices.list_ports", ports)
    monkeypatch.setattr("app.agents.executive.run_messages", lambda *a, **k: next(answers))
    response = client.post(
        "/api/main-agent/projects/" + project["id"] + "/chat",
        json={"message": "check my esp32 connection"},
    )
    body = response.json()
    assert response.status_code == 200
    assert len(discoveries) == 2  # Safe preflight and the parsed model tool call.
    assert body["steps"][1]["tool"] == "list_serial_ports"
    assert body["steps"][1]["status"] == "ok"
    assert "COM7" in body["text"]
    assert "tool_call" not in body["text"]


def test_native_serial_open_still_requires_permission(monkeypatch):
    project, _ = _setup()
    monkeypatch.setattr("app.agents.executive.run_messages", lambda *a, **k:
        '<|tool_call>call:serial_open{"device":"COM7"}<tool_call|>')
    response = client.post(
        "/api/main-agent/projects/" + project["id"] + "/chat",
        json={"message": "check my esp32 connection", "allow_hardware": False},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "waiting_approval"
    assert response.json()["steps"][-1]["permission"] == "hardware.serial"


@pytest.mark.parametrize("recovers", [True, False])
def test_executive_does_not_display_malformed_serial_action(monkeypatch, recovers):
    project, _ = _setup()
    calls = []
    model_calls = []

    def execute(**kwargs):
        calls.append(kwargs["name"])
        assert kwargs["name"] == "list_serial_ports"
        return [{"device": "COM7", "manufacturer": "Espressif"}]

    def respond(agent, messages, endpoint=None):
        model_calls.append(1)
        if len(model_calls) == 1 or not recovers:
            return r'{"type":"tool","tool":"serial\_open","args":{"device":"COM2"}}'
        assert "Invalid action JSON" in messages[-1]["content"]
        assert any("COM7" in item["content"] for item in messages)
        return json.dumps({
            "type": "reply",
            "message": "Found an Espressif device on COM7; a connection has not been verified.",
        })

    monkeypatch.setattr("app.agents.executive.tools.execute", execute)
    monkeypatch.setattr("app.agents.executive.run_messages", respond)
    response = client.post(
        "/api/main-agent/projects/" + project["id"] + "/chat",
        json={"message": "can you access my esp32", "allow_hardware": True},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == ("completed" if recovers else "error")
    assert "serial\\_open" not in body["text"]
    assert calls == ["list_serial_ports"]
    assert len(model_calls) == (2 if recovers else 4)
    stored = client.get("/api/main-agent/projects/" + project["id"] + "/messages").json()
    assert stored[-1]["content"] == body["text"]


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
    assert body["steps"][0]["type"] == "tool_preflight"
    assert body["steps"][0]["tool"] == "list_serial_ports"
    serial_open_step = next(
        step
        for step in body["steps"]
        if step.get("tool") == "serial_open"
    )
    assert serial_open_step["permission"] == "hardware.serial"



def test_effective_executive_tool_endpoint_reports_runtime_tools():
    project, _workers = _setup()

    response = client.get(
        "/api/tools/main-agent/" + project["id"] + "/effective"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["project_id"] == project["id"]
    assert body["count"] > 0
    names = {item["name"] for item in body["tools"]}
    assert "read_file" in names
    assert "run_tests" in names
    assert "list_serial_ports" in names

    removed = client.put(
        "/api/tools/main-agent/"
        + project["id"]
        + "/read_file",
        json={"enabled": False},
    )
    assert removed.status_code == 200

    after = client.get(
        "/api/tools/main-agent/" + project["id"] + "/effective"
    )
    assert after.status_code == 200
    after_names = {item["name"] for item in after.json()["tools"]}
    assert "read_file" not in after_names


def test_executive_rejects_false_no_tool_access_reply(monkeypatch):
    project, _workers = _setup()
    calls = {"count": 0}

    def fake_run_messages(agent, messages, endpoint=None):
        calls["count"] += 1
        if calls["count"] == 1:
            assert "read_file" in messages[0]["content"]
            assert "list_files" in messages[0]["content"]
            return json.dumps({
                "type": "reply",
                "message": "I cannot access the project files directly.",
            })
        if calls["count"] == 2:
            assert "RUNTIME CORRECTION" in messages[-1]["content"]
            return json.dumps({
                "type": "tool",
                "tool": "list_files",
                "args": {"path": "."},
            })
        return json.dumps({
            "type": "reply",
            "message": "I accessed the project and found README.md.",
        })

    def fake_execute(**kwargs):
        assert kwargs["name"] == "list_files"
        assert "list_files" in kwargs["allowed_names"]
        return [{"path": "README.md", "type": "file"}]

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
            "message": "List files in the project.",
            "allow_terminal": False,
            "allow_delete": False,
            "allow_network": False,
            "allow_hardware": False,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["text"] == "I accessed the project and found README.md."
    assert body["steps"][0]["type"] == "runtime_guard"
    assert body["steps"][0]["reason"] == "false_tool_denial"
    assert body["steps"][1]["type"] == "tool"
    assert body["steps"][1]["tool"] == "list_files"
    assert body["steps"][1]["status"] == "ok"



def test_main_agent_assignment_set_is_atomic_and_exact():
    project, _workers = _setup()

    response = client.put(
        "/api/tools/main-agent/"
        + project["id"]
        + "/bulk/set",
        json={
            "tool_names": [
                "list_files",
                "read_file",
                "list_serial_ports",
            ]
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 3
    assert {
        item["name"] for item in body["tools"]
    } == {
        "list_files",
        "read_file",
        "list_serial_ports",
    }

    listed = client.get(
        "/api/tools/main-agent/" + project["id"]
    )
    assert listed.status_code == 200
    assigned = {
        item["name"]
        for item in listed.json()
        if item["assigned"] and item["globally_enabled"]
    }
    assert assigned == {
        "list_files",
        "read_file",
        "list_serial_ports",
    }

    effective = client.get(
        "/api/tools/main-agent/" + project["id"] + "/effective"
    )
    assert effective.status_code == 200
    assert {
        item["name"] for item in effective.json()["tools"]
    } == assigned


def test_main_agent_assignment_set_rejects_unknown_tool():
    project, _workers = _setup()

    response = client.put(
        "/api/tools/main-agent/"
        + project["id"]
        + "/bulk/set",
        json={"tool_names": ["not_a_real_tool"]},
    )
    assert response.status_code == 400
    assert "Unknown tools" in response.json()["detail"]



def test_health_reports_current_runtime_revision():
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["runtime"] == "agent-man"
    assert body["api_revision"] == "mission-control-v2"
    assert body["features"]["executive_tool_assignment_set"] is True
    assert body["features"]["elevenlabs_voice"] is True
    assert body["features"]["mission_control_effective_access"] is True


def test_exact_bulk_set_route_is_registered():
    project, _workers = _setup()
    path = (
        "/api/tools/main-agent/"
        + project["id"]
        + "/bulk/set"
    )

    response = client.put(
        path,
        json={"tool_names": ["list_files", "read_file"]},
    )
    assert response.status_code == 200
    assert {
        item["name"] for item in response.json()["tools"]
    } == {"list_files", "read_file"}


def test_executive_blocks_peer_fanout_without_explicit_request(
    monkeypatch,
):
    project, workers = _setup()
    calls = {"count": 0, "peer_called": False}

    def fake_run_messages(agent, messages, endpoint=None):
        calls["count"] += 1
        if calls["count"] == 1:
            return json.dumps({
                "type": "delegate_peers",
                "agent_ids": [
                    workers["Developer"]["id"],
                    workers["Tester"]["id"],
                ],
                "task": "Work on the feature together.",
            })
        if calls["count"] == 2:
            assert "RUNTIME CORRECTION" in messages[-1]["content"]
            return json.dumps({
                "type": "delegate_agent",
                "agent_id": workers["Developer"]["id"],
                "task": "Implement the feature.",
            })
        return json.dumps({
            "type": "reply",
            "message": "Developer completed the feature.",
        })

    def fake_peer_task(**kwargs):
        calls["peer_called"] = True
        raise AssertionError("peer fan-out should be blocked")

    def fake_execute_agent(**kwargs):
        return {
            "status": "completed",
            "text": "Implemented.",
            "steps": [],
        }

    monkeypatch.setattr(
        "app.agents.executive.run_messages",
        fake_run_messages,
    )
    monkeypatch.setattr(
        "app.agents.executive.run_peer_task",
        fake_peer_task,
    )
    monkeypatch.setattr(
        "app.agents.executive.execute_agent",
        fake_execute_agent,
    )

    response = client.post(
        "/api/main-agent/projects/" + project["id"] + "/chat",
        json={
            "message": "Implement this feature.",
            "allow_terminal": False,
            "allow_delete": False,
            "allow_network": False,
            "allow_hardware": False,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert calls["peer_called"] is False
    assert body["steps"][0]["type"] == "runtime_guard"
    assert body["steps"][0]["reason"] == "parallel_not_requested"
    assert body["steps"][1]["type"] == "delegate_agent"


def test_executive_allows_peer_fanout_when_explicitly_requested(
    monkeypatch,
):
    project, workers = _setup()
    calls = {"count": 0, "peer_called": False}

    def fake_run_messages(agent, messages, endpoint=None):
        calls["count"] += 1
        if calls["count"] == 1:
            return json.dumps({
                "type": "delegate_peers",
                "agent_ids": [
                    workers["Developer"]["id"],
                    workers["Tester"]["id"],
                ],
                "task": "Work in parallel.",
            })
        return json.dumps({
            "type": "reply",
            "message": "Parallel work completed.",
        })

    def fake_peer_task(*, task, **kwargs):
        calls["peer_called"] = True
        task.status = "completed"

    monkeypatch.setattr(
        "app.agents.executive.run_messages",
        fake_run_messages,
    )
    monkeypatch.setattr(
        "app.agents.executive.run_peer_task",
        fake_peer_task,
    )

    response = client.post(
        "/api/main-agent/projects/" + project["id"] + "/chat",
        json={
            "message": "Have multiple agents work in parallel on this.",
            "allow_terminal": False,
            "allow_delete": False,
            "allow_network": False,
            "allow_hardware": False,
        },
    )
    assert response.status_code == 200
    assert calls["peer_called"] is True



def test_executive_intelligently_discovers_esp32_before_opening(monkeypatch):
    project, _workers = _setup()
    calls = {"llm": 0, "tools": []}

    def fake_execute(**kwargs):
        calls["tools"].append(
            (kwargs["name"], dict(kwargs["arguments"]))
        )
        if kwargs["name"] == "list_serial_ports":
            return [
                {
                    "device": "COM7",
                    "description": "USB JTAG/serial debug unit",
                    "manufacturer": "Espressif",
                    "vid": 0x303A,
                    "pid": 0x1001,
                    "active_session_id": None,
                }
            ]
        if kwargs["name"] == "serial_open":
            assert kwargs["arguments"]["device"] == "COM7"
            return {
                "session_id": "session-1",
                "device": "COM7",
                "baudrate": 115200,
                "is_open": True,
            }
        if kwargs["name"] == "serial_read":
            assert kwargs["arguments"]["session_id"] == "session-1"
            return {
                "session_id": "session-1",
                "device": "COM7",
                "bytes_read": 5,
                "text": "ready",
                "hex": "72 65 61 64 79",
            }
        raise AssertionError("Unexpected tool " + kwargs["name"])

    def fake_run_messages(agent, messages, endpoint=None):
        calls["llm"] += 1

        if calls["llm"] == 1:
            system = messages[0]["content"]
            assert "Intent: serial_hardware" in system
            assert "list_serial_ports -> serial_open -> serial_read" in system
            preflight = messages[-1]["content"]
            assert "RUNTIME PREFLIGHT RESULT" in preflight
            assert "COM7" in preflight
            assert "Espressif" in preflight
            return json.dumps({
                "type": "tool",
                "tool": "serial_open",
                "args": {
                    "device": "COM7",
                    "baudrate": 115200,
                },
            })

        if calls["llm"] == 2:
            return json.dumps({
                "type": "tool",
                "tool": "serial_read",
                "args": {
                    "session_id": "session-1",
                    "max_bytes": 128,
                },
            })

        return json.dumps({
            "type": "reply",
            "message": "ESP32 is available on COM7 and reports ready.",
        })

    monkeypatch.setattr(
        "app.agents.executive.tools.execute",
        fake_execute,
    )
    monkeypatch.setattr(
        "app.agents.executive.run_messages",
        fake_run_messages,
    )

    response = client.post(
        "/api/main-agent/projects/" + project["id"] + "/chat",
        json={
            "message": "Access my ESP32 and read its serial output.",
            "allow_terminal": False,
            "allow_delete": False,
            "allow_network": False,
            "allow_hardware": True,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["steps"][0]["type"] == "tool_preflight"
    assert body["steps"][0]["tool"] == "list_serial_ports"
    assert body["steps"][1]["tool"] == "serial_open"
    assert body["steps"][2]["tool"] == "serial_read"
    assert calls["tools"][0][0] == "list_serial_ports"



def test_executive_emits_live_tool_activity(monkeypatch):
    from app.events.bus import events

    project, _workers = _setup()
    answers = iter([
        json.dumps({
            "type": "tool",
            "tool": "list_files",
            "args": {"path": "."},
        }),
        json.dumps({
            "type": "reply",
            "message": "I inspected the project files.",
        }),
    ])

    monkeypatch.setattr(
        "app.agents.executive.run_messages",
        lambda *args, **kwargs: next(answers),
    )
    monkeypatch.setattr(
        "app.agents.executive.tools.execute",
        lambda **kwargs: [
            {"path": "README.md", "type": "file"}
        ],
    )

    cursor = events.current_sequence()
    response = client.post(
        "/api/main-agent/projects/" + project["id"] + "/chat",
        json={
            "message": "List files in the project.",
            "allow_terminal": False,
            "allow_delete": False,
            "allow_network": False,
            "allow_hardware": False,
        },
    )

    assert response.status_code == 200

    _, emitted = events.wait_since(
        cursor,
        timeout=0,
        project_id=project["id"],
    )
    activity = [
        event
        for event in emitted
        if event["type"] == "executive.activity"
        and event.get("label") == "list_files"
    ]

    assert [event["status"] for event in activity] == [
        "started",
        "completed",
    ]
    assert activity[0]["message"] == "Running list_files"



def test_effective_executive_tools_report_mission_control_gates():
    project, _workers = _setup()

    response = client.get(
        "/api/tools/main-agent/" + project["id"] + "/effective"
    )
    assert response.status_code == 200
    tools = {
        item["name"]: item
        for item in response.json()["tools"]
    }

    assert tools["read_file"]["approval_gate"] is None
    assert tools["read_file"]["permission"] is None

    assert tools["run_command"]["approval_gate"] == "exec"
    assert (
        tools["run_command"]["permission"]
        == "terminal.execute"
    )

    assert tools["http_get"]["approval_gate"] == "net"
    assert (
        tools["http_get"]["permission"]
        == "network.internet"
    )

    assert tools["serial_open"]["approval_gate"] == "hw"
    assert (
        tools["serial_open"]["permission"]
        == "hardware.serial"
    )

    assert tools["delete_path"]["approval_gate"] == "delete"
    assert (
        tools["delete_path"]["permission"]
        == "project.files.delete"
    )
