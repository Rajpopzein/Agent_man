from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
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
from app.api.schemas import (
    MeetingRoomCreate,
    MeetingRoomInstructionInput,
    MeetingRoomView,
)
from app.events.bus import events
from app.persistence.database import get_session
from app.persistence.models import AgentRecord, ProjectRecord


router = APIRouter(
    prefix="/api/meeting-rooms",
    tags=["meeting-rooms"],
)


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
def instruct_room_agent(
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

    member_map = {
        agent.id: (member, agent)
        for member, agent in room_member_agents(db, room.id)
        if member.active
    }
    pair = member_map.get(body.agent_id)
    if pair is None:
        raise HTTPException(
            422,
            "Selected agent is not an active member of this meeting room.",
        )
    _member, agent = pair

    append_room_message(
        db,
        room_id=room.id,
        sender_type="user",
        sender_name="You",
        kind="instruction",
        content=body.instruction,
    )

    agent.state = "assigned"
    room.updated_at = datetime.now(timezone.utc)
    db.commit()

    events.emit(
        "executive.activity",
        project_id=room.project_id,
        room_id=room.id,
        agent_id="main-agent:" + room.project_id,
        agent_name="Agent Man",
        phase="delegation",
        status="connecting",
        label=agent.name,
        message="Connecting with " + agent.name + " in " + room.title + ".",
    )
    events.emit(
        "agent.delegated",
        project_id=room.project_id,
        room_id=room.id,
        agent_id=agent.id,
        agent_name=agent.name,
        agent_role=agent.role,
        task=body.instruction[:500],
        state="assigned",
    )

    try:
        job = background_jobs.start_agent(
            project_id=room.project_id,
            room_id=room.id,
            agent_id=agent.id,
            agent_name=agent.name,
            agent_role=agent.role,
            task=body.instruction,
            allow_terminal=body.allow_terminal,
            allow_delete=body.allow_delete,
            allow_network=body.allow_network,
            allow_hardware=body.allow_hardware,
        )
    except ValueError as exc:
        append_room_message(
            db,
            room_id=room.id,
            sender_type="executive",
            sender_id="main-agent:" + room.project_id,
            sender_name="Agent Man",
            kind="assignment_error",
            content=(
                "I could not start "
                + agent.name
                + ": "
                + str(exc)
            ),
        )
        raise HTTPException(409, str(exc)) from exc

    append_room_message(
        db,
        room_id=room.id,
        sender_type="executive",
        sender_id="main-agent:" + room.project_id,
        sender_name="Agent Man",
        kind="assignment",
        content=(
            "Assigned this instruction to "
            + agent.name
            + ". I am tracking the job progress in this room."
        ),
        job_id=str(job["id"]),
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

    active = [
        job
        for job in _room_jobs(room.project_id, room.id)
        if str(job.get("status") or "")
        in {"queued", "running", "stopping", "waiting_approval"}
    ]
    if active:
        raise HTTPException(
            409,
            "Stop or finish active room jobs before closing the meeting room.",
        )

    room = close_meeting_room(db, room)
    return _view(db, room)
