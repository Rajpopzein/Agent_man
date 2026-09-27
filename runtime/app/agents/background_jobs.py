from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from threading import RLock
from uuid import uuid4

from app.agents.executor import execute_agent
from app.events.bus import events
from app.persistence.database import SessionLocal
from app.persistence.models import AgentRecord, ProjectRecord
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

    def _update(
        self,
        job_id: str,
        **changes: object,
    ) -> dict[str, object]:
        with self._lock:
            job = self._jobs[job_id]
            job.update(changes)
            return dict(job)

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
                job["result_text"]
                or job["error"]
                or ""
            )
            if detail:
                detail = " ".join(detail.split())[:500]
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
                + (f"; latest={detail}" if detail else "")
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
