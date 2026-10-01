from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.permissions import ApprovalRequired, PermissionDenied
from app.main import app
from app.sandbox.filesystem import ProjectFilesystem
from app.tools.registry import TOOL_DEFINITIONS, tools

client = TestClient(app)


def _agent():
    suffix = str(uuid4())[:8]
    connection = client.post(
        "/api/ai/connections",
        json={
            "name": "Tools " + suffix,
            "provider_id": "lmstudio",
            "default_model": "test-model",
        },
    )
    assert connection.status_code == 201

    project = client.post(
        "/api/projects",
        json={
            "name": "Tools Project " + suffix,
            "workspace_path": "D:\\AgentMan\\tool-tests\\" + suffix,
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
                "connection_id": connection.json()["id"],
                "model": "test-model",
            },
        },
    )
    assert agent.status_code == 201
    return agent.json()


def test_planned_builtin_tools_are_registered():
    names = {tool.name for tool in TOOL_DEFINITIONS}
    assert {
        "list_files",
        "read_file",
        "write_file",
        "edit_file",
        "search_files",
        "delete_path",
        "run_command",
        "git_status",
        "git_diff",
        "git_commit",
        "run_tests",
        "run_build",
        "lint",
        "check_port",
        "allocate_port",
        "list_processes",
        "start_process",
        "read_process_output",
        "stop_process",
        "http_get",
        "list_serial_ports",
        "serial_open",
        "serial_list_sessions",
        "serial_read",
        "serial_write",
        "serial_close",
    } <= names


def test_agent_tools_can_be_unassigned():
    agent = _agent()
    listed = client.get("/api/tools/agents/" + agent["id"])
    assert listed.status_code == 200
    assert any(
        item["name"] == "write_file" and item["assigned"]
        for item in listed.json()
    )

    changed = client.put(
        "/api/tools/agents/" + agent["id"] + "/write_file",
        json={"enabled": False},
    )
    assert changed.status_code == 200
    assert changed.json()["assigned"] is False


def test_runtime_rejects_unassigned_tool(tmp_path: Path):
    with pytest.raises(PermissionDenied):
        tools.execute(
            name="write_file",
            arguments={"path": "blocked.txt", "content": "no"},
            workspace_path=str(tmp_path),
            allowed_names={"read_file"},
        )


def test_delete_requires_explicit_approval(tmp_path: Path):
    fs = ProjectFilesystem(str(tmp_path))
    fs.write_file("delete-me.txt", "temporary")

    with pytest.raises(ApprovalRequired):
        fs.delete_path("delete-me.txt")

    result = fs.delete_path(
        "delete-me.txt",
        approvals={"project.files.delete"},
    )
    assert result["deleted"] is True



def test_internet_requires_explicit_approval(tmp_path: Path):
    with pytest.raises(ApprovalRequired) as exc:
        tools.execute(
            name="http_get",
            arguments={"url": "https://example.com"},
            workspace_path=str(tmp_path),
            approvals=set(),
            allowed_names={"http_get"},
        )
    assert exc.value.permission.value == "network.internet"



def test_serial_open_requires_hardware_approval(tmp_path: Path):
    with pytest.raises(ApprovalRequired) as exc:
        tools.execute(
            name="serial_open",
            arguments={"device": "COM3", "baudrate": 115200},
            workspace_path=str(tmp_path),
            approvals=set(),
            allowed_names={"serial_open"},
        )
    assert exc.value.permission.value == "hardware.serial"

def test_agent_api_tools_are_executive_only_by_default():
    agent = _agent()
    project_id = agent["project_id"]

    worker_tools = client.get(
        "/api/tools/agents/" + agent["id"]
    )
    assert worker_tools.status_code == 200
    worker_by_name = {
        item["name"]: item
        for item in worker_tools.json()
    }

    executive_tools = client.get(
        "/api/tools/main-agent/" + project_id
    )
    assert executive_tools.status_code == 200
    executive_by_name = {
        item["name"]: item
        for item in executive_tools.json()
    }

    api_names = {
        "api_list_agents",
        "api_get_agent",
        "api_create_agent",
        "api_update_agent",
        "api_delete_agent",
        "api_set_agent_tool",
        "api_list_ai_connections",
    }
    assert api_names <= set(worker_by_name)
    assert api_names <= set(executive_by_name)
    assert all(
        worker_by_name[name]["assigned"] is False
        for name in api_names
    )
    assert all(
        executive_by_name[name]["assigned"] is True
        for name in api_names
    )


def test_executive_agent_api_tool_can_inspect_and_update_worker():
    agent = _agent()
    project_id = agent["project_id"]

    listed = tools.execute(
        name="api_list_agents",
        arguments={},
        workspace_path=".",
        project_id=project_id,
        allowed_names={"api_list_agents"},
    )
    found = next(
        item
        for item in listed["agents"]
        if item["id"] == agent["id"]
    )
    assert found["name"] == agent["name"]

    updated = tools.execute(
        name="api_update_agent",
        arguments={
            "agent_id": agent["id"],
            "changes": {
                "role": "Reviewer",
                "context": "Review implementation and tests.",
            },
        },
        workspace_path=".",
        project_id=project_id,
        allowed_names={"api_update_agent"},
    )
    assert updated["agent"]["role"] == "Reviewer"
    assert (
        updated["agent"]["context"]
        == "Review implementation and tests."
    )

    inspected = tools.execute(
        name="api_get_agent",
        arguments={"agent_id": agent["id"]},
        workspace_path=".",
        project_id=project_id,
        allowed_names={"api_get_agent"},
    )
    assert inspected["agent"]["role"] == "Reviewer"


def test_executive_agent_delete_tool_requires_destructive_approval():
    agent = _agent()

    with pytest.raises(ApprovalRequired) as exc:
        tools.execute(
            name="api_delete_agent",
            arguments={"agent_id": agent["id"]},
            workspace_path=".",
            project_id=agent["project_id"],
            approvals=set(),
            allowed_names={"api_delete_agent"},
        )

    assert exc.value.permission.value == "project.files.delete"


def test_workers_cannot_be_given_executive_agent_api_tools():
    agent = _agent()

    with pytest.raises(ValueError, match="Executive-only"):
        tools.execute(
            name="api_set_agent_tool",
            arguments={
                "agent_id": agent["id"],
                "tool_name": "api_update_agent",
                "enabled": True,
            },
            workspace_path=".",
            project_id=agent["project_id"],
            allowed_names={"api_set_agent_tool"},
        )

