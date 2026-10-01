import pytest
import json
from contextlib import contextmanager
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes import router
from app.persistence.database import Base, get_session
from app.persistence.models import AIConnectionRecord, AgentRecord, ProjectRecord
from app.agents.executive_configuration import execute_configuration_action
from app.agents.executive import run_main_agent
from app.persistence.models import MainAgentConfigRecord


@pytest.fixture
def configured_agent():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        project = ProjectRecord(name="Settings test", workspace_path=".")
        connection = AIConnectionRecord(name="New connection", provider_id="lmstudio", endpoint="http://localhost:1234/v1")
        db.add_all([project, connection])
        db.flush()
        agent = AgentRecord(project_id=project.id, name="Original", role="Developer", context="Original instructions",
                            provider_id="openai", connection_id="old", model="old-model", temperature_milli=700)
        db.add(agent)
        db.commit()
        agent_id, project_id, connection_id = agent.id, project.id, connection.id
    app = FastAPI()
    app.include_router(router)

    def session():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_session] = session
    with TestClient(app) as client:
        yield client, agent_id, project_id, connection_id
    engine.dispose()


def test_update_agent_configuration_persists(configured_agent):
    client, agent_id, project_id, connection_id = configured_agent
    response = client.patch(f"/api/agents/{agent_id}", json={
        "name": " Reviewer ", "role": "Tester", "context": "Review changes",
        "llm": {"connection_id": connection_id, "provider_id": "ignored",
                "endpoint": "http://ignored", "model": " new-model ",
                "temperature": 0.7, "context_limit": 8192, "cloud_fallback_allowed": True},
    })
    assert response.status_code == 200
    saved = client.get(f"/api/projects/{project_id}/agents").json()[0]
    assert saved["name"] == "Reviewer"
    assert saved["role"] == "Tester"
    assert saved["context"] == "Review changes"
    assert saved["llm"] == {
        "connection_id": connection_id, "provider_id": "lmstudio", "endpoint": "http://localhost:1234/v1",
        "model": "new-model", "temperature": 0.7, "context_limit": 8192, "cloud_fallback_allowed": True,
    }


def test_context_only_update_preserves_model(configured_agent):
    client, agent_id, _, _ = configured_agent
    response = client.patch(f"/api/agents/{agent_id}", json={"context": "Updated instructions"})
    assert response.status_code == 200
    assert response.json()["llm"]["model"] == "old-model"
    assert response.json()["llm"]["temperature"] == 0.7


@pytest.mark.parametrize("connection,model,status", [("missing", "model", 404), (None, "   ", 422)])
def test_invalid_configuration_does_not_change_agent(configured_agent, connection, model, status):
    client, agent_id, project_id, connection_id = configured_agent
    response = client.patch(f"/api/agents/{agent_id}", json={
        "name": "Should not persist",
        "llm": {"connection_id": connection or connection_id, "provider_id": "lmstudio", "model": model},
    })
    assert response.status_code == status
    saved = client.get(f"/api/projects/{project_id}/agents").json()[0]
    assert saved["name"] == "Original"
    assert saved["llm"]["model"] == "old-model"


def test_executive_inspects_and_updates_one_agent(configured_agent, monkeypatch):
    client, agent_id, project_id, connection_id = configured_agent
    actions = iter([
        {"type": "inspect_agent", "agent_id": agent_id},
        {"type": "list_ai_connections"},
        {"type": "configure_agent", "agent_id": agent_id,
         "changes": {"role": "Reviewer", "llm": {"connection_id": connection_id, "model": "review-model"}}},
        {"type": "reply", "message": "The agent configuration is saved."},
    ])
    prompts = []

    def respond(proxy, messages):
        prompts.append(list(messages))
        return json.dumps(next(actions))

    monkeypatch.setattr("app.agents.executive.run_messages", respond)
    with contextmanager(client.app.dependency_overrides[get_session])() as db:
        config = MainAgentConfigRecord(project_id=project_id, connection_id=connection_id,
                                      provider_id="lmstudio", model="executive", temperature_milli=200)
        db.add(config)
        db.commit()
        result = run_main_agent(project=db.get(ProjectRecord, project_id), config=config,
                                message="Change the worker role and model configuration", db=db,
                                allow_terminal=False, allow_delete=False,
                                allow_network=False, allow_hardware=False)
        assert result["status"] == "completed"
        assert [step["type"] for step in result["steps"]][:3] == ["inspect_agent", "list_ai_connections", "configure_agent"]
        assert all(step["status"] == "ok" for step in result["steps"][:3])
        saved = db.get(AgentRecord, agent_id)
        assert saved.role == "Reviewer"
        assert saved.model == "review-model"
        assert saved.temperature_milli == 700
        assert saved.context == "Original instructions"
        assert "inspect_agent" in prompts[0][0]["content"]
        assert "Original instructions" in prompts[1][-1]["content"]


@pytest.mark.parametrize("kind", ["inspect_agent", "configure_agent"])
def test_executive_cannot_access_other_project_agent(configured_agent, kind):
    client, agent_id, _, _ = configured_agent
    with contextmanager(client.app.dependency_overrides[get_session])() as db:
        with pytest.raises(LookupError, match="this project"):
            execute_configuration_action(db, "another-project", {
                "type": kind, "agent_id": agent_id, "changes": {"name": "Wrong"},
            })
        assert db.get(AgentRecord, agent_id).name == "Original"


@pytest.mark.parametrize("changes", [
    {"name": "   "}, {"role": "   "}, {"llm": {"temperature": 4}},
    {"llm": {"connection_id": "missing"}}, {"state": "completed"},
    {"llm": {"api_key": "not-allowed"}}, {"llm": {"context_limit": 1}},
])
def test_executive_rejects_invalid_configuration(configured_agent, changes):
    client, agent_id, project_id, _ = configured_agent
    with contextmanager(client.app.dependency_overrides[get_session])() as db:
        with pytest.raises((ValueError, LookupError)):
            execute_configuration_action(db, project_id, {
                "type": "configure_agent", "agent_id": agent_id, "changes": changes,
            })
        assert db.get(AgentRecord, agent_id).name == "Original"


def test_process_monitor_scopes_list_and_output(configured_agent, monkeypatch, tmp_path):
    client, _, project_id, _ = configured_agent
    with contextmanager(client.app.dependency_overrides[get_session])() as db:
        db.get(ProjectRecord, project_id).workspace_path = str(tmp_path / "project")
        db.commit()
    monkeypatch.setattr("app.api.routes.processes.list", lambda: [
        {"id": "owned", "workspace_path": str(tmp_path / "project")},
        {"id": "other", "workspace_path": str(tmp_path / "other")},
    ])
    reads = []

    def output(process_id):
        reads.append(process_id)
        return "test output"

    monkeypatch.setattr("app.api.routes.processes.read_output", output)
    assert client.get(f"/api/runtime/processes?project_id={project_id}").json() == [
        {"id": "owned", "workspace_path": str(tmp_path / "project")},
    ]
    assert client.get(f"/api/runtime/processes/owned/output?project_id={project_id}").json() == {"output": "test output"}
    assert client.get(f"/api/runtime/processes/other/output?project_id={project_id}").status_code == 404
    assert client.get("/api/runtime/processes?project_id=missing").status_code == 404
    assert reads == ["owned"]
