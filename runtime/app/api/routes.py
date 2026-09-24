from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.api.schemas import AgentCreate, AgentView, LLMConfigInput, ProjectCreate, ProjectView
from app.core.config import settings
from app.persistence.database import get_session
from app.persistence.models import AgentRecord, ProjectRecord

router=APIRouter()

@router.get("/health")
def health():
    return {"status":"healthy","runtime":"agent-man","version":settings.version}

@router.post("/api/projects", response_model=ProjectView, status_code=status.HTTP_201_CREATED)
def create_project(body: ProjectCreate, db: Session=Depends(get_session)):
    row=ProjectRecord(name=body.name, workspace_path=body.workspace_path)
    db.add(row); db.commit(); db.refresh(row)
    return row

@router.get("/api/projects", response_model=list[ProjectView])
def list_projects(db: Session=Depends(get_session)):
    return db.scalars(select(ProjectRecord).order_by(ProjectRecord.created_at.desc())).all()

@router.post("/api/agents", response_model=AgentView, status_code=status.HTTP_201_CREATED)
def create_agent(body: AgentCreate, db: Session=Depends(get_session)):
    if db.get(ProjectRecord, body.project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    row=AgentRecord(project_id=body.project_id,name=body.name,role=body.role,provider_id=body.llm.provider_id,connection_id=body.llm.connection_id,model=body.llm.model,context_limit=body.llm.context_limit,temperature_milli=round(body.llm.temperature*1000),cloud_fallback_allowed=body.llm.cloud_fallback_allowed)
    db.add(row); db.commit(); db.refresh(row)
    return _agent_view(row)

@router.get("/api/projects/{project_id}/agents", response_model=list[AgentView])
def list_agents(project_id: str, db: Session=Depends(get_session)):
    rows=db.scalars(select(AgentRecord).where(AgentRecord.project_id==project_id).order_by(AgentRecord.created_at)).all()
    return [_agent_view(row) for row in rows]

def _agent_view(row: AgentRecord) -> AgentView:
    return AgentView(id=row.id,project_id=row.project_id,name=row.name,role=row.role,state=row.state,llm=LLMConfigInput(provider_id=row.provider_id,connection_id=row.connection_id,model=row.model,context_limit=row.context_limit,temperature=row.temperature_milli/1000,cloud_fallback_allowed=row.cloud_fallback_allowed))
