from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from threading import RLock
from uuid import uuid4

from app.agents.executor import execute_agent
from app.agents.meeting_rooms import append_room_message
from app.agents.orchestration import execute_workflow_run
from app.agents.reinforcement import record_reward
from app.events.bus import events
from app.persistence.database import SessionLocal
from app.persistence.models import (
    AgentRecord,
    AgentTaskHistoryRecord,
    ProjectRecord,
    WorkflowRecord,
    WorkflowRunRecord,
)
from app.providers.connections import bind_agent_connection


ACTIVE_STATUSES = {"queued", "running", "stopping", "waiting_approval", "waiting_capability"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _timestamp(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _persist_agent_task(job: dict[str, object]) -> None:
    agent_id = str(job.get("agent_id") or "")
    if not agent_id or agent_id.startswith("workflow:"):
        return

    try:
        with SessionLocal() as db:
            row = db.get(
                AgentTaskHistoryRecord,
                str(job["id"]),
            )
            if row is None:
                row = AgentTaskHistoryRecord(
                    id=str(job["id"]),
                    project_id=str(job["project_id"]),
                    agent_id=agent_id,
                    agent_name=str(job.get("agent_name") or "Worker"),
                    agent_role=str(job.get("agent_role") or ""),
                    room_id=(
                        str(job.get("room_id"))
                        if job.get("room_id")
                        else None
                    ),
                    task=str(job.get("task") or ""),
                    status=str(job.get("status") or "queued"),
                    created_at=(
                        _timestamp(job.get("created_at"))
                        or datetime.now(timezone.utc)
                    ),
                )
                db.add(row)

            row.agent_name = str(
                job.get("agent_name") or row.agent_name
            )
            row.agent_role = str(
                job.get("agent_role") or row.agent_role
            )
            row.room_id = (
                str(job.get("room_id"))
                if job.get("room_id")
                else None
            )
            row.task = str(job.get("task") or row.task)
            row.status = str(job.get("status") or row.status)
            row.current_action = str(
                job.get("current_action") or ""
            )[:4000]
            row.current_tool = str(
                job.get("current_tool") or ""
            )[:160]
            row.result_text = str(
                job.get("result_text") or ""
            )[:12000]
            row.error = str(job.get("error") or "")[:4000]
            row.step_count = int(job.get("step_count") or 0)
            row.started_at = _timestamp(job.get("started_at"))
            row.completed_at = _timestamp(
                job.get("completed_at")
            )
            row.updated_at = (
                _timestamp(job.get("updated_at"))
                or datetime.now(timezone.utc)
            )
            db.commit()
    except Exception:
        # Work execution must never fail because audit persistence failed.
        pass


class BackgroundJobSupervisor:
    def __init__(self, max_workers: int = 6):
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="agent-man-worker",
        )
        self._lock = RLock()
        self._jobs: dict[str, dict[str, object]] = {}
        self._futures: dict[str, Future] = {}

    def start_agent(
        self,
        *,
        project_id: str,
        agent_id: str,
        agent_name: str,
        agent_role: str,
        task: str,
        allow_terminal: bool = False,
        allow_delete: bool = False,
        allow_network: bool = False,
        allow_hardware: bool = False,
        room_id: str | None = None,
    ) -> dict[str, object]:
        with self._lock:
            for job in self._jobs.values():
                if (
                    job["project_id"] == project_id
                    and job["agent_id"] == agent_id
                    and job["status"] in ACTIVE_STATUSES
                ):
                    raise ValueError(
                        f"{agent_name} already has an active background job."
                    )

            job_id = str(uuid4())
            job = {
                "id": job_id,
                "project_id": project_id,
                "room_id": room_id,
                "agent_id": agent_id,
                "agent_name": agent_name,
                "agent_role": agent_role,
                "task": " ".join(task.split())[:4000],
                "status": "queued",
                "created_at": _now(),
                "started_at": None,
                "completed_at": None,
                "result_text": "",
                "step_count": 0,
                "error": "",
                "current_phase": "queued",
                "current_action": "Waiting to start.",
                "current_tool": "",
                "current_detail": "",
                "current_next_step": "",
                "updated_at": _now(),
                "stop_requested": False,
            }
            self._jobs[job_id] = job
            _persist_agent_task(job)
            self._futures[job_id] = self._executor.submit(
                self._run_agent,
                job_id,
                project_id,
                agent_id,
                task,
                allow_terminal,
                allow_delete,
                allow_network,
                allow_hardware,
            )

        events.emit(
            "background_job.queued",
            project_id=project_id,
            job_id=job_id,
            agent_id=agent_id,
            agent_name=agent_name,
            agent_role=agent_role,
            room_id=room_id,
            status="queued",
            task=job["task"],
            message=f"{agent_name} queued in background.",
        )
        return self.get(job_id) or dict(job)



    def start_workflow(
        self,
        *,
        project_id: str,
        workflow_id: str,
        workflow_name: str,
        task: str,
        allow_terminal: bool = False,
        allow_delete: bool = False,
        allow_network: bool = False,
        allow_hardware: bool = False,
    ) -> dict[str, object]:
        job_id = str(uuid4())
        agent_id = "workflow:" + workflow_id
        job = {
            "id": job_id,
            "project_id": project_id,
            "room_id": None,
            "agent_id": agent_id,
            "agent_name": workflow_name,
            "agent_role": "Workflow",
            "task": " ".join(task.split())[:4000],
            "status": "queued",
            "created_at": _now(),
            "started_at": None,
            "completed_at": None,
            "result_text": "",
            "step_count": 0,
            "error": "",
            "current_phase": "queued",
            "current_action": "Waiting to start.",
            "current_tool": "",
            "current_detail": "",
            "current_next_step": "",
            "updated_at": _now(),
            "stop_requested": False,
        }
        with self._lock:
            self._jobs[job_id] = job
            self._futures[job_id] = self._executor.submit(
                self._run_workflow,
                job_id,
                project_id,
                workflow_id,
                task,
                allow_terminal,
                allow_delete,
                allow_network,
                allow_hardware,
            )

        events.emit(
            "background_job.queued",
            project_id=project_id,
            job_id=job_id,
            agent_id=agent_id,
            agent_name=workflow_name,
            agent_role="Workflow",
            status="queued",
            task=job["task"],
            message=f"{workflow_name} workflow queued in background.",
        )
        return self.get(job_id) or dict(job)

    def _run_workflow(
        self,
        job_id: str,
        project_id: str,
        workflow_id: str,
        task: str,
        allow_terminal: bool,
        allow_delete: bool,
        allow_network: bool,
        allow_hardware: bool,
    ) -> None:
        job = self._update(
            job_id,
            status="running",
            started_at=_now(),
        )
        events.emit(
            "background_job.started",
            project_id=project_id,
            job_id=job_id,
            agent_id=job["agent_id"],
            agent_name=job["agent_name"],
            agent_role="Workflow",
            status="running",
            task=job["task"],
            message=f"{job['agent_name']} workflow is running in background.",
        )

        try:
            with SessionLocal() as db:
                workflow = db.get(WorkflowRecord, workflow_id)
                if workflow is None or workflow.project_id != project_id:
                    raise ValueError("Workflow not found")

                run = WorkflowRunRecord(
                    workflow_id=workflow.id,
                    project_id=project_id,
                    status="created",
                    current_node_id=workflow.start_node_id,
                    input_prompt=task,
                    last_output="",
                    step_count=0,
                )
                db.add(run)
                db.commit()

                execute_workflow_run(
                    run=run,
                    db=db,
                    allow_terminal=allow_terminal,
                    allow_delete=allow_delete,
                    allow_network=allow_network,
                    allow_hardware=allow_hardware,
                )

                status = str(run.status)
                result_text = str(run.last_output or "")
                step_count = int(run.step_count or 0)

            terminal_status = (
                "completed"
                if status in {
                    "completed",
                    "completed_with_errors",
                }
                else status
            )
            updated = self._update(
                job_id,
                status=terminal_status,
                completed_at=_now(),
                result_text=result_text[:12000],
                step_count=step_count,
                current_phase=terminal_status,
                current_action=(
                    "Workflow finished."
                    if terminal_status == "completed"
                    else "Workflow stopped with status " + terminal_status + "."
                ),
                current_detail=result_text[:2000],
            )
            events.emit(
                "background_job.completed",
                project_id=project_id,
                job_id=job_id,
                agent_id=updated["agent_id"],
                agent_name=updated["agent_name"],
                agent_role="Workflow",
                status=terminal_status,
                result_text=updated["result_text"],
                step_count=updated["step_count"],
                message=(
                    f"{updated['agent_name']} workflow finished: "
                    f"{terminal_status}."
                ),
            )
        except Exception as exc:
            updated = self._update(
                job_id,
                status="error",
                completed_at=_now(),
                error=str(exc)[:2000],
                current_phase="error",
                current_action="Worker failed.",
                current_detail=str(exc)[:2000],
            )
            try:
                with SessionLocal() as reward_db:
                    record_reward(
                        reward_db,
                        project_id=project_id,
                        agent_id=agent_id,
                        agent_name=str(updated["agent_name"]),
                        tool_name=str(updated.get("current_tool") or "") or None,
                        source="background_job",
                        outcome="error",
                        task=task,
                        note=str(exc)[:2000],
                        reference_id=job_id,
                    )
            except Exception:
                pass

            events.emit(
                "background_job.error",
                project_id=project_id,
                job_id=job_id,
                agent_id=updated["agent_id"],
                agent_name=updated["agent_name"],
                agent_role="Workflow",
                status="error",
                error=updated["error"],
                message=f"{updated['agent_name']} workflow failed.",
            )

    def _update(
        self,
        job_id: str,
        **changes: object,
    ) -> dict[str, object]:
        with self._lock:
            job = self._jobs[job_id]
            changes.setdefault("updated_at", _now())
            job.update(changes)
            snapshot = dict(job)
        _persist_agent_task(snapshot)
        return snapshot

    def _progress_callback(self, job_id: str):
        def update_progress(payload: dict[str, object]) -> None:
            previous = self.get(job_id) or {}
            previous_next = str(
                previous.get("current_next_step") or ""
            ).strip()
            next_step = str(
                payload.get("next_step") or ""
            ).strip()[:500]
            updated = self._update(
                job_id,
                current_phase=str(payload.get("phase") or "working"),
                current_action=str(payload.get("action") or "")[:500],
                current_tool=str(payload.get("tool") or "")[:160],
                current_detail=str(payload.get("detail") or "")[:2000],
                current_next_step=next_step,
            )
            events.emit(
                "background_job.progress",
                project_id=updated["project_id"],
                job_id=updated["id"],
                agent_id=updated["agent_id"],
                agent_name=updated["agent_name"],
                agent_role=updated["agent_role"],
                room_id=updated.get("room_id"),
                status=updated["status"],
                current_phase=updated["current_phase"],
                current_action=updated["current_action"],
                current_tool=updated["current_tool"],
                current_detail=updated["current_detail"],
                current_next_step=updated["current_next_step"],
                updated_at=updated["updated_at"],
                message=updated["current_action"],
            )
            if next_step and next_step != previous_next:
                events.emit(
                    "executive.activity",
                    project_id=updated["project_id"],
                    agent_id="main-agent:" + str(updated["project_id"]),
                    agent_name="Agent Man",
                    phase="next_step",
                    status="working",
                    label=updated["agent_name"],
                    message=(
                        str(updated["agent_name"])
                        + " next: "
                        + next_step
                    ),
                    worker_agent_id=updated["agent_id"],
                    next_step=next_step,
                )

        return update_progress

    def _run_agent(
        self,
        job_id: str,
        project_id: str,
        agent_id: str,
        task: str,
        allow_terminal: bool,
        allow_delete: bool,
        allow_network: bool,
        allow_hardware: bool,
    ) -> None:
        if self.stop_requested(job_id):
            self._mark_stopped(job_id)
            return

        job = self._update(
            job_id,
            status="running",
            started_at=_now(),
        )
        events.emit(
            "background_job.started",
            project_id=project_id,
            job_id=job_id,
            agent_id=agent_id,
            agent_name=job["agent_name"],
            agent_role=job["agent_role"],
            room_id=job.get("room_id"),
            status="running",
            task=job["task"],
            message=f"{job['agent_name']} is working in background.",
        )

        try:
            with SessionLocal() as db:
                project = db.get(ProjectRecord, project_id)
                agent = db.get(AgentRecord, agent_id)
                if project is None:
                    raise ValueError("Project not found")
                if agent is None:
                    raise ValueError("Worker agent not found")

                bind_agent_connection(agent, db)
                result = execute_agent(
                    agent=agent,
                    project=project,
                    prompt=task,
                    db=db,
                    allow_terminal=allow_terminal,
                    allow_delete=allow_delete,
                    allow_network=allow_network,
                    allow_hardware=allow_hardware,
                    progress=self._progress_callback(job_id),
                    should_stop=lambda: self.stop_requested(job_id),
                )

            status = str(result.get("status", "completed"))
            if status == "stopped":
                self._mark_stopped(job_id)
                return

            terminal_status = (
                status
                if status in {
                    "waiting_approval",
                    "waiting_capability",
                    "turn_limit",
                    "error",
                    "stopped",
                }
                else "completed"
            )
            result_steps = result.get("steps", [])
            approval_step = next(
                (
                    step
                    for step in reversed(result_steps)
                    if str(step.get("status", ""))
                    == "approval_required"
                ),
                {},
            )
            approval_tool = str(
                approval_step.get("tool") or ""
            )
            approval_permission = str(
                approval_step.get("permission") or ""
            )

            updated = self._update(
                job_id,
                status=terminal_status,
                completed_at=_now(),
                result_text=str(result.get("text", ""))[:12000],
                step_count=len(result_steps),
                current_phase=terminal_status,
                current_action=(
                    "Finished the assigned task."
                    if terminal_status == "completed"
                    else (
                        "Waiting for approval to use "
                        + approval_tool
                        + "."
                        if terminal_status == "waiting_approval"
                        and approval_tool
                        else "Worker stopped with status "
                        + terminal_status
                        + "."
                    )
                ),
                current_tool=(
                    approval_tool
                    if terminal_status == "waiting_approval"
                    else str(
                        self.get(job_id).get("current_tool", "")
                        if self.get(job_id)
                        else ""
                    )
                ),
                current_detail=(
                    approval_permission
                    if terminal_status == "waiting_approval"
                    and approval_permission
                    else str(result.get("text", ""))[:2000]
                ),
            )

            reward_tool = str(
                updated.get("current_tool") or ""
            ) or None
            with SessionLocal() as reward_db:
                record_reward(
                    reward_db,
                    project_id=project_id,
                    agent_id=agent_id,
                    agent_name=str(updated["agent_name"]),
                    tool_name=reward_tool,
                    source="background_job",
                    outcome=terminal_status,
                    task=task,
                    note=str(result.get("text", ""))[:2000],
                    reference_id=job_id,
                )

            if terminal_status == "waiting_approval":
                approval_message = (
                    f"{updated['agent_name']} is waiting for approval"
                    + (
                        " to use " + approval_tool
                        if approval_tool
                        else ""
                    )
                    + (
                        ". Required permission: "
                        + approval_permission
                        if approval_permission
                        else ""
                    )
                    + ". Approve it to continue the same background task."
                )
                events.emit(
                    "background_job.approval_required",
                    project_id=project_id,
                    job_id=job_id,
                    agent_id=agent_id,
                    agent_name=updated["agent_name"],
                    agent_role=updated["agent_role"],
                    room_id=updated.get("room_id"),
                    status="waiting_approval",
                    tool=approval_tool,
                    permission=approval_permission,
                    current_phase="waiting_approval",
                    current_action=updated["current_action"],
                    current_tool=approval_tool,
                    current_detail=approval_permission,
                    updated_at=updated["updated_at"],
                    message=approval_message,
                )
                events.emit(
                    "executive.activity",
                    project_id=project_id,
                    agent_id="main-agent:" + project_id,
                    agent_name="Agent Man",
                    phase="approval",
                    status="waiting_approval",
                    label=updated["agent_name"],
                    message=approval_message,
                )
            else:
                room_id = str(updated.get("room_id") or "").strip()
                if room_id:
                    try:
                        with SessionLocal() as room_db:
                            append_room_message(
                                room_db,
                                room_id=room_id,
                                sender_type="agent",
                                sender_id=agent_id,
                                sender_name=str(updated["agent_name"]),
                                kind="task_result",
                                content=(
                                    str(updated.get("result_text") or "")
                                    or (
                                        str(updated["agent_name"])
                                        + " finished with status "
                                        + terminal_status
                                        + "."
                                    )
                                ),
                                job_id=job_id,
                            )
                    except Exception:
                        pass
                events.emit(
                    "background_job.completed",
                    project_id=project_id,
                    job_id=job_id,
                    agent_id=agent_id,
                    agent_name=updated["agent_name"],
                    agent_role=updated["agent_role"],
                    room_id=updated.get("room_id"),
                    status=terminal_status,
                    result_text=updated["result_text"],
                    step_count=updated["step_count"],
                    message=(
                        f"{updated['agent_name']} finished: {terminal_status}."
                    ),
                )
        except Exception as exc:
            updated = self._update(
                job_id,
                status="error",
                completed_at=_now(),
                error=str(exc)[:2000],
                current_phase="error",
                current_action="Worker failed.",
                current_detail=str(exc)[:2000],
            )
            try:
                with SessionLocal() as db:
                    agent = db.get(AgentRecord, agent_id)
                    if agent is not None:
                        agent.state = "failed"
                        db.commit()
            except Exception:
                pass

            events.emit(
                "background_job.error",
                project_id=project_id,
                job_id=job_id,
                agent_id=agent_id,
                agent_name=updated["agent_name"],
                agent_role=updated["agent_role"],
                room_id=updated.get("room_id"),
                status="error",
                error=updated["error"],
                message=f"{updated['agent_name']} background job failed.",
            )

    def stop_requested(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            return bool(job and job.get("stop_requested"))

    def _mark_stopped(
        self,
        job_id: str,
    ) -> dict[str, object]:
        updated = self._update(
            job_id,
            status="stopped",
            completed_at=_now(),
            current_phase="stopped",
            current_action="Stopped by the user.",
            current_next_step="",
            stop_requested=True,
        )
        agent_id = str(updated.get("agent_id") or "")
        try:
            with SessionLocal() as db:
                agent = db.get(AgentRecord, agent_id)
                if agent is not None:
                    agent.state = "idle"
                    db.commit()
        except Exception:
            pass

        room_id = str(updated.get("room_id") or "").strip()
        if room_id:
            try:
                with SessionLocal() as room_db:
                    append_room_message(
                        room_db,
                        room_id=room_id,
                        sender_type="executive",
                        sender_id="main-agent:" + str(updated["project_id"]),
                        sender_name="Agent Man",
                        kind="task_stopped",
                        content=(
                            str(updated["agent_name"])
                            + " was stopped manually."
                        ),
                        job_id=job_id,
                    )
            except Exception:
                pass

        events.emit(
            "background_job.stopped",
            project_id=updated["project_id"],
            room_id=updated.get("room_id"),
            job_id=job_id,
            agent_id=updated["agent_id"],
            agent_name=updated["agent_name"],
            agent_role=updated["agent_role"],
            status="stopped",
            current_phase="stopped",
            current_action=updated["current_action"],
            updated_at=updated["updated_at"],
            message=str(updated["agent_name"]) + " stopped.",
        )
        events.emit(
            "executive.activity",
            project_id=updated["project_id"],
            agent_id="main-agent:" + str(updated["project_id"]),
            agent_name="Agent Man",
            phase="stop",
            status="stopped",
            label=updated["agent_name"],
            room_id=updated.get("room_id"),
            message=str(updated["agent_name"]) + " was stopped by the user.",
        )
        return updated

    def stop(
        self,
        job_id: str,
    ) -> dict[str, object]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise LookupError("Background job not found")

            status = str(job.get("status") or "")
            if status in {
                "completed",
                "error",
                "turn_limit",
                "stopped",
            }:
                return dict(job)

            job["stop_requested"] = True
            future = self._futures.get(job_id)

            if status in {"waiting_approval", "waiting_capability"}:
                immediate = True
            elif status == "queued" and future is not None and future.cancel():
                immediate = True
            else:
                immediate = False
                job.update(
                    {
                        "status": "stopping",
                        "current_phase": "stopping",
                        "current_action": (
                            "Stop requested. Waiting for the current "
                            "model or tool step to reach a safe boundary."
                        ),
                        "updated_at": _now(),
                    }
                )
                snapshot = dict(job)

        if immediate:
            return self._mark_stopped(job_id)

        _persist_agent_task(snapshot)
        events.emit(
            "background_job.stop_requested",
            project_id=snapshot["project_id"],
            room_id=snapshot.get("room_id"),
            job_id=job_id,
            agent_id=snapshot["agent_id"],
            agent_name=snapshot["agent_name"],
            agent_role=snapshot["agent_role"],
            status="stopping",
            current_phase="stopping",
            current_action=snapshot["current_action"],
            updated_at=snapshot["updated_at"],
            message=(
                str(snapshot["agent_name"])
                + " will stop at the next safe execution boundary."
            ),
        )
        return snapshot

    def approve_and_resume(
        self,
        job_id: str,
    ) -> dict[str, object]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise LookupError("Background job not found")
            if str(job.get("status", "")) != "waiting_approval":
                raise ValueError(
                    "Only a job waiting for approval can be resumed"
                )
            agent_id = str(job.get("agent_id") or "")
            if agent_id.startswith("workflow:"):
                raise ValueError(
                    "Workflow approval resume is not supported yet"
                )

            permission = str(
                job.get("current_detail") or ""
            ).strip()
            allow_terminal = permission == "terminal.execute"
            allow_delete = permission == "project.files.delete"
            allow_network = permission == "network.internet"
            allow_hardware = permission == "hardware.serial"
            if not any(
                (
                    allow_terminal,
                    allow_delete,
                    allow_network,
                    allow_hardware,
                )
            ):
                raise ValueError(
                    "Waiting job does not expose a resumable permission"
                )

            project_id = str(job["project_id"])
            task = str(job["task"])
            agent_name = str(job["agent_name"])
            agent_role = str(job["agent_role"])
            job.update(
                {
                    "status": "queued",
                    "completed_at": None,
                    "result_text": "",
                    "error": "",
                    "current_phase": "queued",
                    "current_action": (
                        "Approval received. Resuming the assigned task."
                    ),
                    "current_detail": permission,
                    "current_next_step": "",
                    "updated_at": _now(),
                    "stop_requested": False,
                }
            )
            self._futures[job_id] = self._executor.submit(
                self._run_agent,
                job_id,
                project_id,
                agent_id,
                task,
                allow_terminal,
                allow_delete,
                allow_network,
                allow_hardware,
            )
            snapshot = dict(job)

        _persist_agent_task(snapshot)
        events.emit(
            "background_job.resumed",
            project_id=project_id,
            job_id=job_id,
            agent_id=agent_id,
            agent_name=agent_name,
            agent_role=agent_role,
            room_id=snapshot.get("room_id"),
            status="queued",
            permission=permission,
            current_phase="queued",
            current_action=snapshot["current_action"],
            current_tool=snapshot["current_tool"],
            current_detail=permission,
            current_next_step="",
            updated_at=snapshot["updated_at"],
            message=(
                agent_name
                + " received approval and is resuming the task."
            ),
        )
        events.emit(
            "executive.activity",
            project_id=project_id,
            agent_id="main-agent:" + project_id,
            agent_name="Agent Man",
            phase="approval",
            status="approved",
            label=agent_name,
            message=(
                agent_name
                + " received approval and is resuming work."
            ),
        )
        return snapshot

    def get(
        self,
        job_id: str,
    ) -> dict[str, object] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job is not None else None

    def list_project(
        self,
        project_id: str,
    ) -> list[dict[str, object]]:
        with self._lock:
            rows = [
                dict(job)
                for job in self._jobs.values()
                if job["project_id"] == project_id
            ]
        rows.sort(
            key=lambda item: str(item["created_at"]),
            reverse=True,
        )
        return rows

    def context_text(
        self,
        project_id: str,
        limit: int = 12,
    ) -> str:
        jobs = self.list_project(project_id)[:limit]
        if not jobs:
            return "(none)"

        lines: list[str] = []
        for job in jobs:
            detail = str(
                job.get("current_detail")
                or job["result_text"]
                or job["error"]
                or ""
            )
            if detail:
                detail = " ".join(detail.split())[:700]
            current_action = " ".join(
                str(job.get("current_action") or "").split()
            )[:500]
            current_tool = str(
                job.get("current_tool") or ""
            )[:160]
            next_step = " ".join(
                str(job.get("current_next_step") or "").split()
            )[:500]
            lines.append(
                "- "
                + str(job["id"])
                + ": "
                + str(job["agent_name"])
                + ((
                    " room=" + str(job.get("room_id"))
                ) if job.get("room_id") else "")
                + " ("
                + str(job["agent_role"])
                + ") ["
                + str(job["status"])
                + "] task="
                + str(job["task"])[:500]
                + "; phase="
                + str(job.get("current_phase") or job["status"])
                + (f"; action={current_action}" if current_action else "")
                + (f"; tool={current_tool}" if current_tool else "")
                + (f"; detail={detail}" if detail else "")
                + (f"; next={next_step}" if next_step else "")
                + "; updated="
                + str(job.get("updated_at") or job["created_at"])
            )
        return "\n".join(lines)

    def wait(
        self,
        job_id: str,
        timeout: float = 10.0,
    ) -> dict[str, object] | None:
        with self._lock:
            future = self._futures.get(job_id)
        if future is not None:
            future.result(timeout=timeout)
        return self.get(job_id)


background_jobs = BackgroundJobSupervisor()
