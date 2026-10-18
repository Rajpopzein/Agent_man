from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from threading import Lock

from sqlalchemy import select

from app.agents.meeting_rooms import append_room_message
from app.agents.multi_agent import run_peer_task
from app.events.bus import events
from app.persistence.database import SessionLocal
from app.persistence.models import (
    AgentRecord,
    MultiAgentParticipantRecord,
    MultiAgentTaskRecord,
)


class RoomCollaborationSupervisor:
    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=4,
            thread_name_prefix="meeting-room",
        )
        self._lock = Lock()
        self._futures: dict[str, Future[None]] = {}
        self._stop_requested: set[str] = set()

    def _should_stop(self, task_id: str) -> bool:
        with self._lock:
            return task_id in self._stop_requested

    def start(
        self,
        task_id: str,
        *,
        allow_delete: bool = False,
    ) -> None:
        with self._lock:
            current = self._futures.get(task_id)
            if current is not None and not current.done():
                return
            self._stop_requested.discard(task_id)
            future = self._executor.submit(
                self._run,
                task_id,
                allow_delete,
            )
            self._futures[task_id] = future

    def stop(self, task_id: str) -> None:
        with self._lock:
            self._stop_requested.add(task_id)

        with SessionLocal() as db:
            task = db.get(MultiAgentTaskRecord, task_id)
            if task is None:
                raise LookupError("Room collaboration not found")
            if task.status in {
                "completed",
                "completed_with_errors",
                "failed",
                "stopped",
            }:
                return
            task.status = "stopping"
            db.commit()
            events.emit(
                "meeting_room.collaboration.stop_requested",
                project_id=task.project_id,
                room_id=task.room_id,
                task_id=task.id,
            )

    def _run(
        self,
        task_id: str,
        allow_delete: bool,
    ) -> None:
        with SessionLocal() as db:
            task = db.get(MultiAgentTaskRecord, task_id)
            if task is None or not task.room_id:
                return

            room_id = task.room_id

            def on_message(
                agent: AgentRecord,
                kind: str,
                message: str,
                round_number: int,
            ) -> None:
                append_room_message(
                    db,
                    room_id=room_id,
                    sender_type="agent",
                    sender_id=agent.id,
                    sender_name=agent.name,
                    kind=(
                        "peer_final"
                        if kind == "final"
                        else "peer_message"
                    ),
                    content=message,
                    job_id=task.id,
                )
                events.emit(
                    "meeting_room.collaboration.message",
                    project_id=task.project_id,
                    room_id=room_id,
                    task_id=task.id,
                    agent_id=agent.id,
                    agent_name=agent.name,
                    kind=kind,
                    round=round_number,
                )

            try:
                result = run_peer_task(
                    task=task,
                    db=db,
                    allow_terminal=True,
                    allow_delete=allow_delete,
                    allow_network=True,
                    allow_hardware=True,
                    should_stop=lambda: self._should_stop(task_id),
                    on_message=on_message,
                )
            except Exception as exc:
                task.status = "failed"
                db.commit()
                append_room_message(
                    db,
                    room_id=room_id,
                    sender_type="executive",
                    sender_id="main-agent:" + task.project_id,
                    sender_name="Agent Man",
                    kind="collaboration_error",
                    content="Room collaboration failed: " + str(exc),
                    job_id=task.id,
                )
                events.emit(
                    "meeting_room.collaboration.error",
                    project_id=task.project_id,
                    room_id=room_id,
                    task_id=task.id,
                    error=str(exc)[:500],
                )
                return
            finally:
                with self._lock:
                    self._futures.pop(task_id, None)
                    self._stop_requested.discard(task_id)

            if result.status in {
                "completed",
                "completed_with_errors",
            }:
                append_room_message(
                    db,
                    room_id=room_id,
                    sender_type="executive",
                    sender_id="main-agent:" + task.project_id,
                    sender_name="Agent Man",
                    kind="collaboration_completed",
                    content=(
                        "The room members independently confirmed the "
                        "shared objective is complete."
                    ),
                    job_id=task.id,
                )
                events.emit(
                    "meeting_room.collaboration.completed",
                    project_id=task.project_id,
                    room_id=room_id,
                    task_id=task.id,
                    status=result.status,
                )
            elif result.status == "waiting_approval":
                append_room_message(
                    db,
                    room_id=room_id,
                    sender_type="executive",
                    sender_id="main-agent:" + task.project_id,
                    sender_name="Agent Man",
                    kind="approval_required",
                    content=(
                        "The room is waiting only on a destructive action "
                        "approval. Normal collaboration remains automatic."
                    ),
                    job_id=task.id,
                )
            elif result.status == "stopped":
                append_room_message(
                    db,
                    room_id=room_id,
                    sender_type="executive",
                    sender_id="main-agent:" + task.project_id,
                    sender_name="Agent Man",
                    kind="collaboration_stopped",
                    content="The room collaboration was stopped.",
                    job_id=task.id,
                )

    def kick(
        self,
        *,
        task_id: str,
        agent_id: str,
    ) -> None:
        with SessionLocal() as db:
            participant = db.scalar(
                select(MultiAgentParticipantRecord).where(
                    MultiAgentParticipantRecord.task_id == task_id,
                    MultiAgentParticipantRecord.agent_id == agent_id,
                )
            )
            if participant is not None:
                participant.status = "kicked"
            agent = db.get(AgentRecord, agent_id)
            if agent is not None:
                agent.state = "idle"
            db.commit()


room_collaborations = RoomCollaborationSupervisor()
