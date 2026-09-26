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
