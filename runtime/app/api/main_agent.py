from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.agents.executive import run_main_agent
from app.api.schemas import (
    MainAgentChatReply,
    MainAgentChatRequest,
    MainAgentConfigInput,
    MainAgentConfigView,
    MainAgentMessageView,
)
from app.persistence.database import get_session
from app.persistence.models import (
    AIConnectionRecord,
    MainAgentConfigRecord,
    MainAgentMessageRecord,
    ProjectRecord,
)

router = APIRouter(prefix="/api/main-agent", tags=["main-agent"])


@router.get("/projects/{project_id}/config")
def get_config(project_id: str, db: Session = Depends(get_session)):
    row = db.get(MainAgentConfigRecord, project_id)
    return config_view(row) if row else None


@router.put("/projects/{project_id}/config", response_model=MainAgentConfigView)
def set_config(project_id: str, body: MainAgentConfigInput, db: Session = Depends(get_session)):
    if db.get(ProjectRecord, project_id) is None:
        raise HTTPException(404, "Project not found")
    connection = db.get(AIConnectionRecord, body.connection_id)
    if connection is None:
        raise HTTPException(404, "AI connection not found")
    row = db.get(MainAgentConfigRecord, project_id)
    if row is None:
        row = MainAgentConfigRecord(project_id=project_id)
        db.add(row)
    row.connection_id = connection.id
    row.provider_id = connection.provider_id
    row.endpoint = connection.endpoint
    row.model = body.model
    row.context_limit = body.context_limit
    row.temperature_milli = round(body.temperature * 1000)
    db.commit()
    db.refresh(row)
    return config_view(row)


@router.get("/projects/{project_id}/messages", response_model=list[MainAgentMessageView])
def messages(project_id: str, db: Session = Depends(get_session)):
    return db.scalars(
        select(MainAgentMessageRecord)
        .where(MainAgentMessageRecord.project_id == project_id)
        .order_by(MainAgentMessageRecord.created_at)
    ).all()


@router.delete("/projects/{project_id}/messages")
def clear_messages(project_id: str, db: Session = Depends(get_session)):
    db.execute(delete(MainAgentMessageRecord).where(MainAgentMessageRecord.project_id == project_id))
    db.commit()
    return {"cleared": True}


@router.post("/projects/{project_id}/chat", response_model=MainAgentChatReply)
def chat(project_id: str, body: MainAgentChatRequest, db: Session = Depends(get_session)):
    project = db.get(ProjectRecord, project_id)
    if project is None:
        raise HTTPException(404, "Project not found")
    config = db.get(MainAgentConfigRecord, project_id)
    if config is None:
        raise HTTPException(409, "Configure Agent Man's executive model first")
    try:
        return run_main_agent(
            project=project,
            config=config,
            message=body.message,
            db=db,
            allow_terminal=body.allow_terminal,
            allow_delete=body.allow_delete,
            allow_network=body.allow_network,
        )
    except Exception as exc:
        raise HTTPException(502, f"Main agent execution error: {exc}") from exc


def config_view(row):
    return MainAgentConfigView(
        project_id=row.project_id,
        connection_id=row.connection_id,
        provider_id=row.provider_id,
        model=row.model,
        endpoint=row.endpoint,
        context_limit=row.context_limit,
        temperature=row.temperature_milli / 1000,
    )
