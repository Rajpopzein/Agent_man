import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.agents.executor import execute_agent
from app.agents.runner import run_agent
from app.api.schemas import AgentCreate, AgentPrompt, AgentReply, AgentRunReply, AgentRunRequest, AgentView, LLMConfigInput, ProjectCreate, ProjectView
from app.core.config import settings
from app.events.bus import events
from app.persistence.database import get_session
from app.persistence.models import (
    AIConnectionRecord,
    AgentRecord,
    AgentToolRecord,
    MultiAgentMessageRecord,
    MultiAgentParticipantRecord,
    ProjectRecord,
    WorkflowNodeRecord,
    WorkflowRunStepRecord,
)
from app.providers.connections import bind_agent_connection
from app.sandbox.filesystem import ProjectFilesystem
from app.sandbox.managed_processes import processes
from app.sandbox.ports import ports
from app.tools.service import ensure_agent_defaults

router = APIRouter()


@router.get("/health")
def health():
    return {
        "status": "healthy",
        "runtime": "agent-man",
        "version": settings.version,
        "api_revision": settings.api_revision,
        "features": {
            "executive_tool_assignment_set": True,
            "executive_effective_tools": True,
            "serial_device_broker": True,
            "elevenlabs_voice": True,
            "mission_control_effective_access": True,
        },
    }


@router.post("/api/projects", response_model=ProjectView, status_code=201)
def create_project(body: ProjectCreate, db: Session = Depends(get_session)):
    row = ProjectRecord(name=body.name, workspace_path=body.workspace_path)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/api/projects", response_model=list[ProjectView])
def list_projects(db: Session = Depends(get_session)):
    return db.scalars(select(ProjectRecord).order_by(ProjectRecord.created_at.desc())).all()


@router.post("/api/agents", response_model=AgentView, status_code=201)
def create_agent(body: AgentCreate, db: Session = Depends(get_session)):
    if db.get(ProjectRecord, body.project_id) is None:
        raise HTTPException(404, "Project not found")
    llm = body.llm
    connection = db.get(AIConnectionRecord, llm.connection_id)
    provider_id = connection.provider_id if connection is not None else llm.provider_id
    endpoint = connection.endpoint if connection is not None else llm.endpoint
    row = AgentRecord(
        project_id=body.project_id,
        name=body.name,
        role=body.role,
        provider_id=provider_id,
        connection_id=llm.connection_id,
        model=llm.model,
        endpoint=endpoint,
        context_limit=llm.context_limit,
        temperature_milli=round(llm.temperature * 1000),
        cloud_fallback_allowed=llm.cloud_fallback_allowed,
    )
    db.add(row)
    db.flush()
    ensure_agent_defaults(db, row.id)
    db.commit()
    db.refresh(row)
    return agent_view(row)


@router.get("/api/projects/{project_id}/agents", response_model=list[AgentView])
def list_agents(project_id: str, db: Session = Depends(get_session)):
    rows = db.scalars(select(AgentRecord).where(AgentRecord.project_id == project_id)).all()
    return [agent_view(row) for row in rows]


@router.delete("/api/agents/{agent_id}")
def delete_agent(agent_id: str, db: Session = Depends(get_session)):
    agent = db.get(AgentRecord, agent_id)
    if agent is None:
        raise HTTPException(404, "Agent not found")

    dependencies: list[str] = []
    if db.scalar(
        select(MultiAgentParticipantRecord.id)
        .where(MultiAgentParticipantRecord.agent_id == agent_id)
        .limit(1)
    ):
        dependencies.append("multi-agent task history")
    if db.scalar(
        select(MultiAgentMessageRecord.id)
        .where(MultiAgentMessageRecord.agent_id == agent_id)
        .limit(1)
    ):
        dependencies.append("multi-agent messages")
    if db.scalar(
        select(WorkflowNodeRecord.id)
        .where(WorkflowNodeRecord.agent_id == agent_id)
        .limit(1)
    ):
        dependencies.append("workflow stages")
    if db.scalar(
        select(WorkflowRunStepRecord.id)
        .where(WorkflowRunStepRecord.agent_id == agent_id)
        .limit(1)
    ):
        dependencies.append("workflow run history")

    if dependencies:
        raise HTTPException(
            409,
            "Agent cannot be deleted because it is referenced by: "
            + ", ".join(sorted(set(dependencies)))
            + ". Remove or replace those references first.",
        )

    db.execute(
        delete(AgentToolRecord).where(
            AgentToolRecord.agent_id == agent_id
        )
    )
    db.delete(agent)
    db.commit()
    events.emit(
        "agent.deleted",
        agent_id=agent_id,
        project_id=agent.project_id,
    )
    return {"deleted": True, "id": agent_id}


@router.get("/api/projects/{project_id}/files")
def list_project_files(project_id: str, path: str = ".", db: Session = Depends(get_session)):
    project = db.get(ProjectRecord, project_id)
    if project is None:
        raise HTTPException(404, "Project not found")
    try:
        return ProjectFilesystem(project.workspace_path).list_files(path)
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/api/agents/{agent_id}/chat", response_model=AgentReply)
def chat(agent_id: str, body: AgentPrompt, db: Session = Depends(get_session)):
    agent = db.get(AgentRecord, agent_id)
    if agent is None:
        raise HTTPException(404, "Agent not found")
    bind_agent_connection(agent, db)
    try:
        return AgentReply(agent_id=agent.id, text=run_agent(agent, body.prompt, body.endpoint))
    except Exception as exc:
        raise HTTPException(502, f"Provider error: {exc}") from exc


@router.post("/api/agents/{agent_id}/execute", response_model=AgentRunReply)
def execute(agent_id: str, body: AgentRunRequest, db: Session = Depends(get_session)):
    agent = db.get(AgentRecord, agent_id)
    if agent is None:
        raise HTTPException(404, "Agent not found")
    project = db.get(ProjectRecord, agent.project_id)
    if project is None:
        raise HTTPException(404, "Project not found")
    bind_agent_connection(agent, db)
    try:
        result = execute_agent(
            agent=agent,
            project=project,
            prompt=body.prompt,
            db=db,
            endpoint=body.endpoint,
            allow_terminal=body.allow_terminal,
            allow_delete=body.allow_delete,
            allow_network=body.allow_network,
            allow_hardware=body.allow_hardware,
        )
        return AgentRunReply(agent_id=agent.id, **result)
    except Exception as exc:
        raise HTTPException(502, f"Agent execution error: {exc}") from exc


@router.get("/api/runtime/processes")
def list_managed_processes():
    return processes.list()


@router.get("/api/runtime/processes/{process_id}/output")
def read_managed_process_output(process_id: str):
    try:
        return {"output": processes.read_output(process_id)}
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/api/runtime/ports/{port}")
def check_runtime_port(port: int):
    return {"port": port, "available": ports.is_available(port)}


@router.post("/api/runtime/ports/allocate")
def allocate_runtime_port(start: int = 8000, end: int = 9000):
    try:
        return {"port": ports.allocate(start, end)}
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(409, str(exc)) from exc


@router.delete("/api/runtime/ports/{port}")
def release_runtime_port(port: int):
    ports.release(port)
    return {"port": port, "released": True}


@router.get("/api/events")
def recent_events(limit: int = 100):
    return events.recent(max(1, min(limit, 500)))


@router.get("/api/events/stream")
async def stream_events(
    request: Request,
    project_id: str | None = None,
):
    async def generate():
        try:
            cursor = int(request.headers.get("last-event-id", ""))
            cursor = max(0, min(cursor, events.current_sequence()))
        except ValueError:
            cursor = events.current_sequence()

        yield ": agent-man-event-stream\n\n"

        while not await request.is_disconnected():
            cursor, batch = await asyncio.to_thread(
                events.wait_since,
                cursor,
                15.0,
                project_id,
            )

            if not batch:
                yield ": keepalive\n\n"
                continue

            for event in batch:
                yield (
                    "id: " + str(event["sequence"]) + "\n"
                    + "data: "
                    + json.dumps(
                        event,
                        ensure_ascii=False,
                        default=str,
                    )
                    + "\n\n"
                )

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def agent_view(row: AgentRecord) -> AgentView:
    return AgentView(
        id=row.id,
        project_id=row.project_id,
        name=row.name,
        role=row.role,
        state=row.state,
        llm=LLMConfigInput(
            provider_id=row.provider_id,
            connection_id=row.connection_id,
            model=row.model,
            endpoint=row.endpoint,
            context_limit=row.context_limit,
            temperature=row.temperature_milli / 1000,
            cloud_fallback_allowed=row.cloud_fallback_allowed,
        ),
    )
