import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.agents.background_jobs import background_jobs
from app.agents.executive import run_main_agent
from app.agents.reinforcement import project_summary, record_reward
from app.api.schemas import (
    AgentTaskHistoryView,
    BackgroundJobView,
    MainAgentChatReply,
    MainAgentChatRequest,
    MainAgentConfigInput,
    MainAgentConfigView,
    MainAgentMessageView,
    ReinforcementEventView,
    ReinforcementFeedbackInput,
    ReinforcementSummaryView,
    SelfUpgradeProposalView,
)
from app.persistence.database import get_session
from app.persistence.models import (
    AIConnectionRecord,
    AgentTaskHistoryRecord,
    MainAgentConfigRecord,
    MainAgentMessageRecord,
    ProjectRecord,
    ReinforcementEventRecord,
    SelfUpgradeProposalRecord,
)

router = APIRouter(prefix="/api/main-agent", tags=["main-agent"])


def _upgrade_view(row: SelfUpgradeProposalRecord) -> SelfUpgradeProposalView:
    def decode(raw: str) -> list[str]:
        try:
            value = json.loads(raw or "[]")
        except json.JSONDecodeError:
            return []
        if not isinstance(value, list):
            return []
        return [str(item) for item in value]

    return SelfUpgradeProposalView(
        id=row.id,
        project_id=row.project_id,
        title=row.title,
        reason=row.reason,
        changes=decode(row.changes_json),
        validation=decode(row.validation_json),
        status=row.status,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


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
            allow_hardware=body.allow_hardware,
        )
    except Exception as exc:
        raise HTTPException(502, f"Main agent execution error: {exc}") from exc


@router.get(
    "/projects/{project_id}/background-jobs",
    response_model=list[BackgroundJobView],
)
def background_job_status(
    project_id: str,
    db: Session = Depends(get_session),
):
    if db.get(ProjectRecord, project_id) is None:
        raise HTTPException(404, "Project not found")
    return background_jobs.list_project(project_id)


@router.get(
    "/projects/{project_id}/task-history",
    response_model=list[AgentTaskHistoryView],
)
def task_history(
    project_id: str,
    agent_id: str | None = None,
    status: str | None = None,
    limit: int = 300,
    db: Session = Depends(get_session),
):
    if db.get(ProjectRecord, project_id) is None:
        raise HTTPException(404, "Project not found")

    query = (
        select(AgentTaskHistoryRecord)
        .where(AgentTaskHistoryRecord.project_id == project_id)
        .order_by(AgentTaskHistoryRecord.created_at.desc())
        .limit(max(1, min(limit, 1000)))
    )
    if agent_id:
        query = query.where(
            AgentTaskHistoryRecord.agent_id == agent_id
        )
    if status:
        query = query.where(
            AgentTaskHistoryRecord.status == status
        )
    return db.scalars(query).all()


@router.post(
    "/projects/{project_id}/background-jobs/{job_id}/stop",
    response_model=BackgroundJobView,
)
def stop_background_job(
    project_id: str,
    job_id: str,
    db: Session = Depends(get_session),
):
    if db.get(ProjectRecord, project_id) is None:
        raise HTTPException(404, "Project not found")
    job = background_jobs.get(job_id)
    if job is None or str(job.get("project_id")) != project_id:
        raise HTTPException(404, "Background job not found")
    try:
        return background_jobs.stop(job_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post(
    "/projects/{project_id}/background-jobs/{job_id}/approve",
    response_model=BackgroundJobView,
)
def approve_background_job(
    project_id: str,
    job_id: str,
    db: Session = Depends(get_session),
):
    if db.get(ProjectRecord, project_id) is None:
        raise HTTPException(404, "Project not found")
    job = background_jobs.get(job_id)
    if job is None or str(job.get("project_id")) != project_id:
        raise HTTPException(404, "Background job not found")
    try:
        return background_jobs.approve_and_resume(job_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc




def _reinforcement_view(row: ReinforcementEventRecord) -> ReinforcementEventView:
    return ReinforcementEventView(
        id=row.id,
        project_id=row.project_id,
        agent_id=row.agent_id,
        agent_name=row.agent_name,
        tool_name=row.tool_name,
        source=row.source,
        outcome=row.outcome,
        reward=row.reward_milli / 1000,
        task=row.task,
        note=row.note,
        reference_id=row.reference_id,
        created_at=row.created_at,
    )


@router.post(
    "/projects/{project_id}/reinforcement/feedback",
    response_model=ReinforcementEventView,
)
def reinforcement_feedback(
    project_id: str,
    body: ReinforcementFeedbackInput,
    db: Session = Depends(get_session),
):
    if db.get(ProjectRecord, project_id) is None:
        raise HTTPException(404, "Project not found")
    if body.value == 0:
        raise HTTPException(422, "Feedback must be positive or negative")

    outcome = "user_positive" if body.value > 0 else "user_negative"
    row = record_reward(
        db,
        project_id=project_id,
        outcome=outcome,
        agent_id=body.agent_id,
        agent_name=body.agent_name,
        tool_name=body.tool_name,
        source="user",
        task=body.task,
        note=body.note,
        reference_id=body.reference_id,
    )
    return _reinforcement_view(row)


@router.get(
    "/projects/{project_id}/reinforcement/summary",
    response_model=ReinforcementSummaryView,
)
def reinforcement_summary(
    project_id: str,
    db: Session = Depends(get_session),
):
    if db.get(ProjectRecord, project_id) is None:
        raise HTTPException(404, "Project not found")
    return project_summary(db, project_id)


@router.get(
    "/projects/{project_id}/upgrades",
    response_model=list[SelfUpgradeProposalView],
)
def upgrades(project_id: str, db: Session = Depends(get_session)):
    if db.get(ProjectRecord, project_id) is None:
        raise HTTPException(404, "Project not found")
    rows = db.scalars(
        select(SelfUpgradeProposalRecord)
        .where(SelfUpgradeProposalRecord.project_id == project_id)
        .order_by(SelfUpgradeProposalRecord.created_at.desc())
    ).all()
    return [_upgrade_view(row) for row in rows]


@router.post(
    "/projects/{project_id}/upgrades/{proposal_id}/approve",
    response_model=SelfUpgradeProposalView,
)
def approve_upgrade(
    project_id: str,
    proposal_id: str,
    db: Session = Depends(get_session),
):
    row = db.get(SelfUpgradeProposalRecord, proposal_id)
    if row is None or row.project_id != project_id:
        raise HTTPException(404, "Upgrade proposal not found")
    if row.status not in {"proposed", "approved"}:
        raise HTTPException(
            409,
            "Only a proposed upgrade can be approved.",
        )
    row.status = "approved"
    db.commit()
    db.refresh(row)
    return _upgrade_view(row)


@router.post(
    "/projects/{project_id}/upgrades/{proposal_id}/reject",
    response_model=SelfUpgradeProposalView,
)
def reject_upgrade(
    project_id: str,
    proposal_id: str,
    db: Session = Depends(get_session),
):
    row = db.get(SelfUpgradeProposalRecord, proposal_id)
    if row is None or row.project_id != project_id:
        raise HTTPException(404, "Upgrade proposal not found")
    if row.status == "applied":
        raise HTTPException(409, "An applied upgrade cannot be rejected.")
    row.status = "rejected"
    db.commit()
    db.refresh(row)
    return _upgrade_view(row)


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
