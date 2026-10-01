from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.background_jobs import background_jobs
from app.agents.meeting_rooms import (
    append_room_message,
    close_meeting_room,
    create_meeting_room,
    get_meeting_room,
    list_meeting_rooms,
    room_member_agents,
    room_snapshot,
)
from app.agents.room_collaboration import room_collaborations
from app.api.schemas import (
    MeetingRoomCreate,
    MeetingRoomInstructionInput,
    MeetingRoomView,
)
from app.events.bus import events
from app.persistence.database import get_session
from app.persistence.models import (
    AgentRecord,
    MeetingRoomMemberRecord,
    MultiAgentMessageRecord,
    MultiAgentParticipantRecord,
    MultiAgentTaskRecord,
    ProjectRecord,
)


router = APIRouter(
    prefix="/api/meeting-rooms",
    tags=["meeting-rooms"],
)

ACTIVE_COLLABORATION_STATUSES = {
    "created",
    "active",
    "executing",
    "waiting_approval",
    "stopping",
}


def _room_jobs(project_id: str, room_id: str) -> list[dict[str, object]]:
    return [
        job
        for job in background_jobs.list_project(project_id)
        if str(job.get("room_id") or "") == room_id
    ]


def _view(db: Session, room) -> dict[str, object]:
    return room_snapshot(
        db,
        room,
        jobs=_room_jobs(room.project_id, room.id),
    )


def _active_collaboration(
    db: Session,
    room_id: str,
) -> MultiAgentTaskRecord | None:
    return db.scalar(
        select(MultiAgentTaskRecord)
        .where(
            MultiAgentTaskRecord.room_id == room_id,
            MultiAgentTaskRecord.status.in_(
                ACTIVE_COLLABORATION_STATUSES
            ),
        )
        .order_by(MultiAgentTaskRecord.created_at.desc())
        .limit(1)
    )


@router.get(
    "/projects/{project_id}",
    response_model=list[MeetingRoomView],
)
def rooms(
    project_id: str,
    db: Session = Depends(get_session),
):
    if db.get(ProjectRecord, project_id) is None:
        raise HTTPException(404, "Project not found")
    return [
        _view(db, room)
        for room in list_meeting_rooms(db, project_id)
    ]


@router.post(
    "",
    response_model=MeetingRoomView,
    status_code=201,
)
def create_room(
    body: MeetingRoomCreate,
    db: Session = Depends(get_session),
):
    try:
        room = create_meeting_room(
            db,
            project_id=body.project_id,
            title=body.title,
            objective=body.objective,
            agent_ids=body.agent_ids,
        )
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return _view(db, room)


@router.get(
    "/{room_id}",
    response_model=MeetingRoomView,
)
def room(
    room_id: str,
    db: Session = Depends(get_session),
):
    try:
        row = get_meeting_room(db, room_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    return _view(db, row)


@router.post(
    "/{room_id}/instructions",
    response_model=MeetingRoomView,
)
def instruct_room(
    room_id: str,
    body: MeetingRoomInstructionInput,
    db: Session = Depends(get_session),
):
    try:
        room = get_meeting_room(db, room_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc

    if room.status != "active":
        raise HTTPException(409, "Meeting room is closed")

    active_members = [
        (member, agent)
        for member, agent in room_member_agents(db, room.id)
        if member.active
    ]
    if not active_members:
        raise HTTPException(
            409,
            "This meeting room has no active worker agents.",
        )

    append_room_message(
        db,
        room_id=room.id,
        sender_type="user",
        sender_name="You",
        kind="instruction",
        content=body.instruction,
    )

    task = _active_collaboration(db, room.id)
    if task is not None:
        db.add(
            MultiAgentMessageRecord(
                task_id=task.id,
                agent_id=None,
                kind="user_instruction",
                round_number=max(1, task.current_round),
                content=body.instruction,
            )
        )
        if task.status == "waiting_approval" and body.allow_delete:
            participants = db.scalars(
                select(MultiAgentParticipantRecord).where(
                    MultiAgentParticipantRecord.task_id == task.id,
                    MultiAgentParticipantRecord.status == "waiting_approval",
                )
            ).all()
            for participant in participants:
                participant.status = "active"
        db.commit()

        append_room_message(
            db,
            room_id=room.id,
            sender_type="executive",
            sender_id="main-agent:" + room.project_id,
            sender_name="Agent Man",
            kind="instruction_added",
            content=(
                "Shared instruction added to the active collaboration. "
                "All active room members will see it in the peer transcript."
            ),
            job_id=task.id,
        )

        if task.status != "waiting_approval" or body.allow_delete:
            room_collaborations.start(
                task.id,
                allow_delete=body.allow_delete,
            )
        db.refresh(room)
        return _view(db, room)

    task = MultiAgentTaskRecord(
        project_id=room.project_id,
        room_id=room.id,
        title=room.title + " collaboration",
        prompt=body.instruction,
        status="created",
        max_rounds=12,
        current_round=0,
    )
    db.add(task)
    db.flush()

    for position, (_member, agent) in enumerate(active_members):
        db.add(
            MultiAgentParticipantRecord(
                task_id=task.id,
                agent_id=agent.id,
                position=position,
                status="ready",
                last_round=0,
            )
        )
        agent.state = "assigned"

    db.commit()
    db.refresh(task)

    member_names = [agent.name for _member, agent in active_members]
    append_room_message(
        db,
        room_id=room.id,
        sender_type="executive",
        sender_id="main-agent:" + room.project_id,
        sender_name="Agent Man",
        kind="collaboration_started",
        content=(
            "Shared collaboration started with "
            + ", ".join(member_names)
            + ". They can read each other's room discussion and will "
            "continue until the objective is complete."
        ),
        job_id=task.id,
    )

    events.emit(
        "meeting_room.collaboration.started",
        project_id=room.project_id,
        room_id=room.id,
        task_id=task.id,
        agent_ids=[agent.id for _member, agent in active_members],
        agent_names=member_names,
        message=(
            "Room collaboration started with "
            + ", ".join(member_names)
            + "."
        ),
    )
    room_collaborations.start(
        task.id,
        allow_delete=body.allow_delete,
    )

    db.refresh(room)
    return _view(db, room)


@router.post(
    "/{room_id}/members/{agent_id}/kick",
    response_model=MeetingRoomView,
)
def kick_room_member(
    room_id: str,
    agent_id: str,
    db: Session = Depends(get_session),
):
    try:
        room = get_meeting_room(db, room_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc

    member = db.scalar(
        select(MeetingRoomMemberRecord).where(
            MeetingRoomMemberRecord.room_id == room.id,
            MeetingRoomMemberRecord.agent_id == agent_id,
        )
    )
    if member is None:
        raise HTTPException(404, "Agent is not a member of this room")
    if not member.active:
        return _view(db, room)

    agent = db.get(AgentRecord, agent_id)
    member.active = False
    if agent is not None:
        agent.state = "idle"

    tasks = db.scalars(
        select(MultiAgentTaskRecord).where(
            MultiAgentTaskRecord.room_id == room.id,
            MultiAgentTaskRecord.status.in_(
                ACTIVE_COLLABORATION_STATUSES
            ),
        )
    ).all()
    for task in tasks:
        participant = db.scalar(
            select(MultiAgentParticipantRecord).where(
                MultiAgentParticipantRecord.task_id == task.id,
                MultiAgentParticipantRecord.agent_id == agent_id,
            )
        )
        if participant is not None:
            participant.status = "kicked"

    db.commit()

    name = agent.name if agent is not None else "Worker"
    append_room_message(
        db,
        room_id=room.id,
        sender_type="executive",
        sender_id="main-agent:" + room.project_id,
        sender_name="Agent Man",
        kind="agent_kicked",
        content=(
            name
            + " was kicked from the meeting room and will not "
            "participate in future collaboration turns."
        ),
    )
    events.emit(
        "meeting_room.member.kicked",
        project_id=room.project_id,
        room_id=room.id,
        agent_id=agent_id,
        agent_name=name,
    )
    db.refresh(room)
    return _view(db, room)


@router.post(
    "/{room_id}/collaborations/{task_id}/stop",
    response_model=MeetingRoomView,
)
def stop_room_collaboration(
    room_id: str,
    task_id: str,
    db: Session = Depends(get_session),
):
    try:
        room = get_meeting_room(db, room_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc

    task = db.get(MultiAgentTaskRecord, task_id)
    if task is None or task.room_id != room.id:
        raise HTTPException(404, "Room collaboration not found")

    try:
        room_collaborations.stop(task.id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc

    append_room_message(
        db,
        room_id=room.id,
        sender_type="executive",
        sender_id="main-agent:" + room.project_id,
        sender_name="Agent Man",
        kind="stop_requested",
        content=(
            "Stop requested for the shared collaboration. "
            "Agents will stop at the next safe turn boundary."
        ),
        job_id=task.id,
    )
    db.refresh(room)
    return _view(db, room)


@router.post(
    "/{room_id}/collaborations/{task_id}/approve-delete",
    response_model=MeetingRoomView,
)
def approve_room_delete(
    room_id: str,
    task_id: str,
    db: Session = Depends(get_session),
):
    try:
        room = get_meeting_room(db, room_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc

    task = db.get(MultiAgentTaskRecord, task_id)
    if task is None or task.room_id != room.id:
        raise HTTPException(404, "Room collaboration not found")
    if task.status != "waiting_approval":
        return _view(db, room)

    participants = db.scalars(
        select(MultiAgentParticipantRecord).where(
            MultiAgentParticipantRecord.task_id == task.id,
            MultiAgentParticipantRecord.status == "waiting_approval",
        )
    ).all()
    for participant in participants:
        participant.status = "active"
    db.commit()

    room_collaborations.start(
        task.id,
        allow_delete=True,
    )
    append_room_message(
        db,
        room_id=room.id,
        sender_type="executive",
        sender_id="main-agent:" + room.project_id,
        sender_name="Agent Man",
        kind="approval_granted",
        content=(
            "Destructive delete approval granted for this collaboration. "
            "The room is continuing."
        ),
        job_id=task.id,
    )
    db.refresh(room)
    return _view(db, room)


@router.post(
    "/{room_id}/close",
    response_model=MeetingRoomView,
)
def close_room(
    room_id: str,
    db: Session = Depends(get_session),
):
    try:
        room = get_meeting_room(db, room_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc

    active_jobs = [
        job
        for job in _room_jobs(room.project_id, room.id)
        if str(job.get("status") or "")
        in {
            "queued",
            "running",
            "stopping",
            "waiting_approval",
        }
    ]
    active_collaboration = _active_collaboration(db, room.id)
    if active_jobs or active_collaboration is not None:
        raise HTTPException(
            409,
            "Stop or finish active room work before closing the meeting room.",
        )

    room = close_meeting_room(db, room)
    return _view(db, room)
