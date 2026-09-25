from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.multi_agent import run_peer_task
from app.api.schemas import (
    MultiAgentMessageView,
    MultiAgentParticipantView,
    MultiAgentRunRequest,
    MultiAgentTaskCreate,
    MultiAgentTaskView,
)
from app.persistence.database import get_session
from app.persistence.models import (
    AgentRecord,
    MultiAgentMessageRecord,
    MultiAgentParticipantRecord,
    MultiAgentTaskRecord,
    ProjectRecord,
)

router = APIRouter(prefix="/api/multi-agent", tags=["multi-agent"])


@router.post("/tasks", response_model=MultiAgentTaskView, status_code=201)
def create_task(body: MultiAgentTaskCreate, db: Session = Depends(get_session)):
    project = db.get(ProjectRecord, body.project_id)
    if project is None:
        raise HTTPException(404, "Project not found")

    agent_ids = list(dict.fromkeys(body.agent_ids))
    if len(agent_ids) < 2:
        raise HTTPException(422, "Select at least two different agents")

    agents = []
    for agent_id in agent_ids:
        agent = db.get(AgentRecord, agent_id)
        if agent is None:
            raise HTTPException(404, f"Agent not found: {agent_id}")
        if agent.project_id != body.project_id:
            raise HTTPException(422, f"Agent {agent.name} does not belong to this project")
        agents.append(agent)

    task = MultiAgentTaskRecord(
        project_id=body.project_id,
        title=body.title,
        prompt=body.prompt,
        status="created",
        max_rounds=body.max_rounds,
        current_round=0,
    )
    db.add(task)
    db.flush()

    for position, agent in enumerate(agents):
        db.add(
            MultiAgentParticipantRecord(
                task_id=task.id,
                agent_id=agent.id,
                position=position,
                status="ready",
                last_round=0,
            )
        )

    db.commit()
    db.refresh(task)
    return task_view(task, db)


@router.get("/projects/{project_id}/tasks", response_model=list[MultiAgentTaskView])
def project_tasks(project_id: str, db: Session = Depends(get_session)):
    rows = db.scalars(
        select(MultiAgentTaskRecord)
        .where(MultiAgentTaskRecord.project_id == project_id)
        .order_by(MultiAgentTaskRecord.created_at.desc())
    ).all()
    return [task_view(row, db) for row in rows]


@router.get("/tasks/{task_id}", response_model=MultiAgentTaskView)
def get_task(task_id: str, db: Session = Depends(get_session)):
    return task_view(require_task(task_id, db), db)


@router.post("/tasks/{task_id}/run", response_model=MultiAgentTaskView)
def run_task(task_id: str, body: MultiAgentRunRequest, db: Session = Depends(get_session)):
    task = require_task(task_id, db)

    if task.status == "waiting_approval" and body.allow_terminal:
        participants = db.scalars(
            select(MultiAgentParticipantRecord).where(
                MultiAgentParticipantRecord.task_id == task.id,
                MultiAgentParticipantRecord.status == "waiting_approval",
            )
        ).all()
        for participant in participants:
            participant.status = "active"
        db.commit()

    try:
        run_peer_task(task=task, db=db, allow_terminal=body.allow_terminal)
    except Exception as exc:
        task.status = "failed"
        db.commit()
        raise HTTPException(502, f"Multi-agent execution error: {exc}") from exc

    db.refresh(task)
    return task_view(task, db)


def require_task(task_id: str, db: Session) -> MultiAgentTaskRecord:
    task = db.get(MultiAgentTaskRecord, task_id)
    if task is None:
        raise HTTPException(404, "Multi-agent task not found")
    return task


def task_view(task: MultiAgentTaskRecord, db: Session) -> MultiAgentTaskView:
    participants = db.scalars(
        select(MultiAgentParticipantRecord)
        .where(MultiAgentParticipantRecord.task_id == task.id)
        .order_by(MultiAgentParticipantRecord.position)
    ).all()
    messages = db.scalars(
        select(MultiAgentMessageRecord)
        .where(MultiAgentMessageRecord.task_id == task.id)
        .order_by(MultiAgentMessageRecord.created_at)
    ).all()

    participant_views = []
    for participant in participants:
        agent = db.get(AgentRecord, participant.agent_id)
        participant_views.append(
            MultiAgentParticipantView(
                agent_id=participant.agent_id,
                agent_name=agent.name if agent else "Missing agent",
                role=agent.role if agent else "unknown",
                position=participant.position,
                status=participant.status,
                last_round=participant.last_round,
            )
        )

    message_views = []
    for message in messages:
        agent = db.get(AgentRecord, message.agent_id) if message.agent_id else None
        message_views.append(
            MultiAgentMessageView(
                id=message.id,
                agent_id=message.agent_id,
                agent_name=agent.name if agent else "Runtime",
                kind=message.kind,
                round_number=message.round_number,
                content=message.content,
                created_at=message.created_at,
            )
        )

    return MultiAgentTaskView(
        id=task.id,
        project_id=task.project_id,
        title=task.title,
        prompt=task.prompt,
        status=task.status,
        max_rounds=task.max_rounds,
        current_round=task.current_round,
        created_at=task.created_at,
        completed_at=task.completed_at,
        participants=participant_views,
        messages=message_views,
    )
