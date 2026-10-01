from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.events.bus import events
from app.persistence.models import (
    AgentRecord,
    MeetingRoomMemberRecord,
    MeetingRoomMessageRecord,
    MeetingRoomRecord,
    ProjectRecord,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def append_room_message(
    db: Session,
    *,
    room_id: str,
    sender_type: str,
    sender_name: str,
    content: str,
    sender_id: str | None = None,
    kind: str = "message",
    job_id: str | None = None,
) -> MeetingRoomMessageRecord:
    row = MeetingRoomMessageRecord(
        room_id=room_id,
        sender_type=sender_type[:32],
        sender_id=sender_id,
        sender_name=sender_name[:160],
        kind=kind[:40],
        content=content.strip()[:20_000],
        job_id=job_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def create_meeting_room(
    db: Session,
    *,
    project_id: str,
    title: str,
    objective: str,
    agent_ids: Iterable[str],
) -> MeetingRoomRecord:
    project = db.get(ProjectRecord, project_id)
    if project is None:
        raise LookupError("Project not found")

    unique_ids: list[str] = []
    seen: set[str] = set()
    for raw in agent_ids:
        agent_id = str(raw).strip()
        if not agent_id or agent_id in seen:
            continue
        seen.add(agent_id)
        unique_ids.append(agent_id)

    if not unique_ids:
        raise ValueError("A meeting room requires at least one worker agent.")
    if len(unique_ids) > 8:
        raise ValueError("A meeting room supports at most eight worker agents.")

    agents = list(
        db.scalars(
            select(AgentRecord).where(
                AgentRecord.id.in_(unique_ids),
                AgentRecord.project_id == project_id,
            )
        ).all()
    )
    by_id = {agent.id: agent for agent in agents}
    missing = [agent_id for agent_id in unique_ids if agent_id not in by_id]
    if missing:
        raise ValueError(
            "Unknown worker agent(s): " + ", ".join(missing)
        )

    clean_title = " ".join(title.split())[:180]
    clean_objective = objective.strip()[:20_000]
    if not clean_title:
        clean_title = "Agent Meeting Room"

    room = MeetingRoomRecord(
        project_id=project_id,
        title=clean_title,
        objective=clean_objective,
        status="active",
    )
    db.add(room)
    db.flush()

    for position, agent_id in enumerate(unique_ids):
        db.add(
            MeetingRoomMemberRecord(
                room_id=room.id,
                agent_id=agent_id,
                position=position,
                active=True,
            )
        )

    names = [by_id[agent_id].name for agent_id in unique_ids]
    db.add(
        MeetingRoomMessageRecord(
            room_id=room.id,
            sender_type="executive",
            sender_id="main-agent:" + project_id,
            sender_name="Agent Man",
            kind="room_created",
            content=(
                "Meeting room created. Connected workers: "
                + ", ".join(names)
                + ". I will track their runtime progress here."
            ),
        )
    )
    db.commit()
    db.refresh(room)

    events.emit(
        "meeting_room.created",
        project_id=project_id,
        room_id=room.id,
        title=room.title,
        objective=room.objective,
        agent_ids=unique_ids,
        agent_names=names,
        message=(
            "Meeting room "
            + room.title
            + " created with "
            + ", ".join(names)
            + "."
        ),
    )
    return room


def get_meeting_room(
    db: Session,
    room_id: str,
) -> MeetingRoomRecord:
    room = db.get(MeetingRoomRecord, room_id)
    if room is None:
        raise LookupError("Meeting room not found")
    return room


def list_meeting_rooms(
    db: Session,
    project_id: str,
) -> list[MeetingRoomRecord]:
    return list(
        db.scalars(
            select(MeetingRoomRecord)
            .where(MeetingRoomRecord.project_id == project_id)
            .order_by(MeetingRoomRecord.updated_at.desc())
        ).all()
    )


def room_member_agents(
    db: Session,
    room_id: str,
) -> list[tuple[MeetingRoomMemberRecord, AgentRecord]]:
    rows = db.execute(
        select(MeetingRoomMemberRecord, AgentRecord)
        .join(
            AgentRecord,
            AgentRecord.id == MeetingRoomMemberRecord.agent_id,
        )
        .where(MeetingRoomMemberRecord.room_id == room_id)
        .order_by(MeetingRoomMemberRecord.position)
    ).all()
    return [(member, agent) for member, agent in rows]


def room_messages(
    db: Session,
    room_id: str,
) -> list[MeetingRoomMessageRecord]:
    return list(
        db.scalars(
            select(MeetingRoomMessageRecord)
            .where(MeetingRoomMessageRecord.room_id == room_id)
            .order_by(MeetingRoomMessageRecord.created_at)
        ).all()
    )


def room_snapshot(
    db: Session,
    room: MeetingRoomRecord,
    *,
    jobs: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    members = room_member_agents(db, room.id)
    messages = room_messages(db, room.id)
    return {
        "id": room.id,
        "project_id": room.project_id,
        "title": room.title,
        "objective": room.objective,
        "status": room.status,
        "created_at": room.created_at,
        "updated_at": room.updated_at,
        "executive": {
            "id": "main-agent:" + room.project_id,
            "name": "Agent Man",
            "role": "Executive",
            "status": "tracking" if room.status == "active" else "closed",
        },
        "members": [
            {
                "agent_id": agent.id,
                "agent_name": agent.name,
                "role": agent.role,
                "state": agent.state,
                "position": member.position,
                "active": member.active,
            }
            for member, agent in members
        ],
        "messages": [
            {
                "id": message.id,
                "sender_type": message.sender_type,
                "sender_id": message.sender_id,
                "sender_name": message.sender_name,
                "kind": message.kind,
                "content": message.content,
                "job_id": message.job_id,
                "created_at": message.created_at,
            }
            for message in messages
        ],
        "jobs": list(jobs or []),
    }


def close_meeting_room(
    db: Session,
    room: MeetingRoomRecord,
) -> MeetingRoomRecord:
    if room.status == "closed":
        return room
    room.status = "closed"
    room.updated_at = _now()
    db.commit()
    append_room_message(
        db,
        room_id=room.id,
        sender_type="executive",
        sender_id="main-agent:" + room.project_id,
        sender_name="Agent Man",
        kind="room_closed",
        content="Meeting room closed. No new worker tasks can be started here.",
    )
    events.emit(
        "meeting_room.closed",
        project_id=room.project_id,
        room_id=room.id,
        title=room.title,
        message="Meeting room closed.",
    )
    db.refresh(room)
    return room
