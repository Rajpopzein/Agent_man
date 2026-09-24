from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.executor import execute_agent
from app.agents.runner import run_agent
from app.api.schemas import AgentCreate, AgentPrompt, AgentReply, AgentRunReply, AgentRunRequest, AgentView, LLMConfigInput, ProjectCreate, ProjectView
from app.core.config import settings
from app.events.bus import events
from app.persistence.database import get_session
from app.persistence.models import AgentRecord, ProjectRecord
from app.sandbox.filesystem import ProjectFilesystem

router = APIRouter()


@router.get("/health")
def health():
    return {"status": "healthy", "runtime": "agent-man", "version": settings.version}


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
    row = AgentRecord(
        project_id=body.project_id,
        name=body.name,
        role=body.role,
        provider_id=llm.provider_id,
        connection_id=llm.connection_id,
        model=llm.model,
        endpoint=llm.endpoint,
        context_limit=llm.context_limit,
        temperature_milli=round(llm.temperature * 1000),
        cloud_fallback_allowed=llm.cloud_fallback_allowed,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return agent_view(row)


@router.get("/api/projects/{project_id}/agents", response_model=list[AgentView])
def list_agents(project_id: str, db: Session = Depends(get_session)):
    rows = db.scalars(select(AgentRecord).where(AgentRecord.project_id == project_id)).all()
    return [agent_view(row) for row in rows]


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
    try:
        result = execute_agent(
            agent=agent,
            project=project,
            prompt=body.prompt,
            endpoint=body.endpoint,
            allow_terminal=body.allow_terminal,
        )
        return AgentRunReply(agent_id=agent.id, **result)
    except Exception as exc:
        raise HTTPException(502, f"Agent execution error: {exc}") from exc


@router.get("/api/events")
def recent_events(limit: int = 100):
    return events.recent(max(1, min(limit, 500)))


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
