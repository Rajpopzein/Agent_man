import json
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.executor import execute_agent
from app.agents.multi_agent import run_peer_task
from app.agents.orchestration import execute_workflow_run
from app.agents.runner import run_messages
from app.persistence.models import (
    AgentRecord,
    MainAgentConfigRecord,
    MainAgentMessageRecord,
    MultiAgentMessageRecord,
    MultiAgentParticipantRecord,
    MultiAgentTaskRecord,
    ProjectRecord,
    WorkflowRecord,
    WorkflowRunRecord,
)
from app.providers.connections import bind_agent_connection

MAX_EXECUTIVE_STEPS = 10
MAX_HISTORY = 20

SYSTEM_PROMPT = """You are Agent Man, the executive agent and primary user interface.
The user talks to you, not directly to worker agents.

You can:
1. reply directly for simple conversational questions;
2. delegate a task to one specialist worker;
3. delegate to multiple peers;
4. run a saved workflow.

You are responsible for the overall objective: inspect worker results, delegate again
when needed, and only give the user a final answer when the overall job is actually
complete. The runtime enforces permissions; never bypass them.

Available workers:
{workers}

Available workflows:
{workflows}

Return exactly one JSON object.

Direct reply:
{{"type":"reply","message":"..."}}

Delegate one worker:
{{"type":"delegate_agent","agent_id":"...","task":"..."}}

Delegate peers:
{{"type":"delegate_peers","agent_ids":["...","..."],"task":"..."}}

Run workflow:
{{"type":"run_workflow","workflow_id":"...","task":"..."}}

Do not ask the user to manually choose Developer/Tester when you can select them.
After a delegation result, reassess the overall objective and either delegate again
or reply with one unified result.
"""


def _parse(raw: str):
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(raw[start:end + 1])
            except json.JSONDecodeError:
                pass
    return {"type": "reply", "message": raw}


def _proxy(config: MainAgentConfigRecord, db: Session):
    proxy = SimpleNamespace(
        id="main-agent:" + config.project_id,
        project_id=config.project_id,
        name="Agent Man",
        role="Executive",
        provider_id=config.provider_id,
        connection_id=config.connection_id,
        model=config.model,
        endpoint=config.endpoint,
        temperature_milli=config.temperature_milli,
    )
    bind_agent_connection(proxy, db)
    return proxy


def _context(project_id: str, db: Session):
    workers = db.scalars(
        select(AgentRecord).where(AgentRecord.project_id == project_id)
    ).all()
    workflows = db.scalars(
        select(WorkflowRecord).where(WorkflowRecord.project_id == project_id)
    ).all()
    worker_text = "\n".join(
        f"- {a.id}: {a.name} ({a.role}) model={a.model}" for a in workers
    ) or "(none)"
    workflow_text = "\n".join(
        f"- {w.id}: {w.name} - {w.description}" for w in workflows
    ) or "(none)"
    return workers, workflows, worker_text, workflow_text


def run_main_agent(
    *,
    project: ProjectRecord,
    config: MainAgentConfigRecord,
    message: str,
    db: Session,
    allow_terminal: bool,
    allow_delete: bool,
    allow_network: bool,
):
    db.add(MainAgentMessageRecord(
        project_id=project.id,
        role="user",
        content=message,
    ))
    db.commit()

    history = list(db.scalars(
        select(MainAgentMessageRecord)
        .where(MainAgentMessageRecord.project_id == project.id)
        .order_by(MainAgentMessageRecord.created_at.desc())
        .limit(MAX_HISTORY)
    ).all())[::-1]

    workers, workflows, worker_text, workflow_text = _context(project.id, db)
    worker_ids = {a.id for a in workers}
    workflow_ids = {w.id for w in workflows}

    messages = [{
        "role": "system",
        "content": SYSTEM_PROMPT.format(
            workers=worker_text,
            workflows=workflow_text,
        ),
    }]
    messages.extend({"role": m.role, "content": m.content} for m in history)
    proxy = _proxy(config, db)
    steps = []

    for _ in range(MAX_EXECUTIVE_STEPS):
        raw = run_messages(proxy, messages)
        action = _parse(raw)
        kind = str(action.get("type", "reply"))

        if kind == "reply":
            text = str(action.get("message", raw)).strip()
            db.add(MainAgentMessageRecord(
                project_id=project.id,
                role="assistant",
                content=text,
            ))
            db.commit()
            return {"status": "completed", "text": text, "steps": steps}

        if kind == "delegate_agent":
            agent_id = str(action.get("agent_id", ""))
            if agent_id not in worker_ids:
                result = {"status": "error", "error": "Unknown worker agent"}
            else:
                agent = db.get(AgentRecord, agent_id)
                bind_agent_connection(agent, db)
                result = execute_agent(
                    agent=agent,
                    project=project,
                    prompt=str(action.get("task", message)),
                    db=db,
                    allow_terminal=allow_terminal,
                    allow_delete=allow_delete,
                    allow_network=allow_network,
                )
            step = {"type": kind, "agent_id": agent_id, "result": result}
            steps.append(step)

        elif kind == "delegate_peers":
            agent_ids = [str(x) for x in action.get("agent_ids", []) if str(x) in worker_ids]
            if len(set(agent_ids)) < 2:
                result = {"status": "error", "error": "At least two valid peers required"}
            else:
                task = MultiAgentTaskRecord(
                    project_id=project.id,
                    title="Agent Man delegated peer task",
                    prompt=str(action.get("task", message)),
                    status="created",
                    max_rounds=12,
                    current_round=0,
                )
                db.add(task)
                db.flush()
                for pos, agent_id in enumerate(dict.fromkeys(agent_ids)):
                    db.add(MultiAgentParticipantRecord(
                        task_id=task.id,
                        agent_id=agent_id,
                        position=pos,
                        status="ready",
                        last_round=0,
                    ))
                db.commit()
                run_peer_task(
                    task=task,
                    db=db,
                    allow_terminal=allow_terminal,
                    allow_delete=allow_delete,
                    allow_network=allow_network,
                )
                finals = db.scalars(
                    select(MultiAgentMessageRecord)
                    .where(
                        MultiAgentMessageRecord.task_id == task.id,
                        MultiAgentMessageRecord.kind == "final",
                    )
                    .order_by(MultiAgentMessageRecord.created_at)
                ).all()
                result = {
                    "status": task.status,
                    "messages": [m.content for m in finals[-6:]],
                }
            step = {"type": kind, "agent_ids": agent_ids, "result": result}
            steps.append(step)

        elif kind == "run_workflow":
            workflow_id = str(action.get("workflow_id", ""))
            if workflow_id not in workflow_ids:
                result = {"status": "error", "error": "Unknown workflow"}
            else:
                workflow = db.get(WorkflowRecord, workflow_id)
                run = WorkflowRunRecord(
                    workflow_id=workflow.id,
                    project_id=project.id,
                    status="created",
                    current_node_id=workflow.start_node_id,
                    input_prompt=str(action.get("task", message)),
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
                )
                result = {
                    "status": run.status,
                    "output": run.last_output,
                    "steps": run.step_count,
                }
            step = {"type": kind, "workflow_id": workflow_id, "result": result}
            steps.append(step)

        else:
            step = {"type": "error", "result": {"error": f"Unknown executive action: {kind}"}}
            steps.append(step)

        messages.append({"role": "assistant", "content": raw})
        messages.append({
            "role": "user",
            "content": "DELEGATION RESULT:\n" + json.dumps(step, default=str)
            + "\nReassess the overall objective. Delegate again if needed, otherwise reply to the user.",
        })

    text = "Executive safety ceiling reached before the overall task completed."
    db.add(MainAgentMessageRecord(project_id=project.id, role="assistant", content=text))
    db.commit()
    return {"status": "step_limit", "text": text, "steps": steps}
