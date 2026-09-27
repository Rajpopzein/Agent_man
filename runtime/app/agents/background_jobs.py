from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from threading import RLock
from uuid import uuid4

from app.agents.executor import execute_agent
from app.agents.orchestration import execute_workflow_run
from app.events.bus import events
from app.persistence.database import SessionLocal
from app.persistence.models import (
    AgentRecord,
    ProjectRecord,
    WorkflowRecord,
    WorkflowRunRecord,
)
from app.providers.connections import bind_agent_connection


ACTIVE_STATUSES = {"queued", "running"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
                "updated_at": _now(),
            }
            self._jobs[job_id] = job
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
            "updated_at": _now(),
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
            return dict(job)

    def _progress_callback(self, job_id: str):
        def update_progress(payload: dict[str, object]) -> None:
            updated = self._update(
                job_id,
                current_phase=str(payload.get("phase") or "working"),
                current_action=str(payload.get("action") or "")[:500],
                current_tool=str(payload.get("tool") or "")[:160],
                current_detail=str(payload.get("detail") or "")[:2000],
            )
            events.emit(
                "background_job.progress",
                project_id=updated["project_id"],
                job_id=updated["id"],
                agent_id=updated["agent_id"],
                agent_name=updated["agent_name"],
                agent_role=updated["agent_role"],
                status=updated["status"],
                current_phase=updated["current_phase"],
                current_action=updated["current_action"],
                current_tool=updated["current_tool"],
                current_detail=updated["current_detail"],
                updated_at=updated["updated_at"],
                message=updated["current_action"],
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
                )

            status = str(result.get("status", "completed"))
            terminal_status = (
                status
                if status in {
                    "waiting_approval",
                    "waiting_capability",
                    "turn_limit",
                    "error",
                }
                else "completed"
            )
            updated = self._update(
                job_id,
                status=terminal_status,
                completed_at=_now(),
                result_text=str(result.get("text", ""))[:12000],
                step_count=len(result.get("steps", [])),
                current_phase=terminal_status,
                current_action=(
                    "Finished the assigned task."
                    if terminal_status == "completed"
                    else "Worker stopped with status " + terminal_status + "."
                ),
                current_detail=str(result.get("text", ""))[:2000],
            )
            events.emit(
                "background_job.completed",
                project_id=project_id,
                job_id=job_id,
                agent_id=agent_id,
                agent_name=updated["agent_name"],
                agent_role=updated["agent_role"],
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
                status="error",
                error=updated["error"],
                message=f"{updated['agent_name']} background job failed.",
            )

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
            lines.append(
                "- "
                + str(job["id"])
                + ": "
                + str(job["agent_name"])
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
