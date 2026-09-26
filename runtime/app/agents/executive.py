import json
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.executor import execute_agent
from app.agents.multi_agent import run_peer_task
from app.agents.orchestration import execute_workflow_run
from app.agents.runner import run_messages
from app.core.permissions import ApprovalRequired, Permission
from app.events.bus import events
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
from app.tools.capabilities import (
    CAPABILITY_TOOLS,
    detect_missing_capability,
)
from app.tools.registry import catalog_for_prompt, tools
from app.tools.service import allowed_main_agent_tool_names

MAX_EXECUTIVE_STEPS = 30
MAX_HISTORY = 20

SYSTEM_PROMPT = """You are Agent Man, the executive agent and primary user interface.
The user talks to you, not directly to worker agents.

You are both an executive coordinator and a direct tool-using agent.

You can:
1. use any runtime tool listed below directly;
2. reply directly for simple conversational questions;
3. delegate a task to one specialist worker;
4. delegate to multiple peers;
5. run a saved workflow.

You are responsible for the overall objective. Use direct tools when you can
efficiently inspect, modify, validate, or operate the project yourself. Delegate
when specialist workers or independent review are useful. After every tool or
delegation result, reassess the overall objective and continue until it is
actually complete.

The runtime enforces permissions. Never bypass approval requirements and never
invent tool results.

Available runtime tools:
{tools}

Available workers:
{workers}

Available workflows:
{workflows}

Return exactly one JSON object and no markdown.

Use an assigned runtime tool:
{{"type":"tool","tool":"TOOL_NAME","args":{{"argument":"value"}}}}

Direct reply:
{{"type":"reply","message":"..."}}

Delegate one worker:
{{"type":"delegate_agent","agent_id":"...","task":"..."}}

Delegate peers:
{{"type":"delegate_peers","agent_ids":["...","..."],"task":"..."}}

Run workflow:
{{"type":"run_workflow","workflow_id":"...","task":"..."}}

If you believe a capability is missing:
{{"type":"capability_request","capability":"internet","reason":"Need current documentation."}}

Rules:
- Do not claim you lack a capability before checking the available runtime tools.
- If a tool attempt fails, inspect the failure and try another safe approach.
- Do not ask the user to manually choose Developer/Tester when you can select them.
- Only reply with the final user-facing result when the overall objective is complete,
  or when a required runtime permission/capability genuinely prevents progress.
"""


def _parse(raw: str):
    raw = raw.strip()
    try:
        action = json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if start >= 0 and end > start:
            try:
                action = json.loads(raw[start:end + 1])
            except json.JSONDecodeError:
                action = {"type": "reply", "message": raw}
        else:
            action = {"type": "reply", "message": raw}

    if not isinstance(action, dict):
        action = {"type": "reply", "message": raw}

    text = str(
        action.get("message")
        or action.get("content")
        or raw
    )
    missing = detect_missing_capability(text)
    if missing and str(action.get("type", "")).lower() == "reply":
        return {
            "type": "capability_request",
            "capability": missing,
            "reason": text,
        }
    return action


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
        f"- {a.id}: {a.name} ({a.role}) model={a.model}"
        for a in workers
    ) or "(none)"
    workflow_text = "\n".join(
        f"- {w.id}: {w.name} - {w.description}"
        for w in workflows
    ) or "(none)"
    return workers, workflows, worker_text, workflow_text


def _store_assistant_message(
    db: Session,
    project_id: str,
    text: str,
) -> None:
    db.add(
        MainAgentMessageRecord(
            project_id=project_id,
            role="assistant",
            content=text,
        )
    )
    db.commit()


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
    db.add(
        MainAgentMessageRecord(
            project_id=project.id,
            role="user",
            content=message,
        )
    )
    db.commit()

    history = list(
        db.scalars(
            select(MainAgentMessageRecord)
            .where(
                MainAgentMessageRecord.project_id == project.id
            )
            .order_by(MainAgentMessageRecord.created_at.desc())
            .limit(MAX_HISTORY)
        ).all()
    )[::-1]

    workers, workflows, worker_text, workflow_text = _context(
        project.id,
        db,
    )
    worker_ids = {a.id for a in workers}
    workflow_ids = {w.id for w in workflows}
    allowed_tools = allowed_main_agent_tool_names(
        db,
        project.id,
    )

    approvals: set[str] = set()
    if allow_terminal:
        approvals.add(Permission.TERMINAL_EXECUTE.value)
    if allow_delete:
        approvals.add(Permission.PROJECT_DELETE.value)
    if allow_network:
        approvals.add(Permission.NETWORK_ACCESS.value)

    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT.format(
                tools=catalog_for_prompt(allowed_tools),
                workers=worker_text,
                workflows=workflow_text,
            ),
        }
    ]
    messages.extend(
        {"role": item.role, "content": item.content}
        for item in history
    )
    proxy = _proxy(config, db)
    steps: list[dict] = []

    for step_number in range(1, MAX_EXECUTIVE_STEPS + 1):
        raw = run_messages(proxy, messages)
        action = _parse(raw)
        kind = str(action.get("type", "reply")).lower()

        if kind == "reply":
            text = str(action.get("message", raw)).strip()
            _store_assistant_message(db, project.id, text)
            return {
                "status": "completed",
                "text": text,
                "steps": steps,
            }

        if kind == "tool":
            tool_name = str(action.get("tool", ""))
            arguments = action.get("args") or {}
            if not isinstance(arguments, dict):
                arguments = {}

            try:
                result = tools.execute(
                    name=tool_name,
                    arguments=arguments,
                    workspace_path=project.workspace_path,
                    approvals=approvals,
                    allowed_names=allowed_tools,
                )
                step = {
                    "type": "tool",
                    "step": step_number,
                    "tool": tool_name,
                    "arguments": arguments,
                    "status": "ok",
                    "result": result,
                }
            except ApprovalRequired as exc:
                step = {
                    "type": "tool",
                    "step": step_number,
                    "tool": tool_name,
                    "arguments": arguments,
                    "status": "approval_required",
                    "permission": exc.permission.value,
                }
                steps.append(step)
                text = (
                    "Agent Man can continue after approval for "
                    + exc.permission.value
                    + "."
                )
                _store_assistant_message(db, project.id, text)
                return {
                    "status": "waiting_approval",
                    "text": text,
                    "steps": steps,
                }
            except Exception as exc:
                step = {
                    "type": "tool",
                    "step": step_number,
                    "tool": tool_name,
                    "arguments": arguments,
                    "status": "error",
                    "error": str(exc),
                }

            steps.append(step)
            messages.append({"role": "assistant", "content": raw})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "TOOL RESULT:\n"
                        + json.dumps(
                            step,
                            ensure_ascii=False,
                            default=str,
                        )
                        + "\nContinue the overall objective. If the tool "
                        "failed, inspect the error and try another safe "
                        "approach when possible."
                    ),
                }
            )
            continue

        if kind == "capability_request":
            capability = str(
                action.get("capability", "")
            ).strip().lower()
            candidates = CAPABILITY_TOOLS.get(
                capability,
                (),
            )
            resolved = [
                tool_name
                for tool_name in candidates
                if tool_name in allowed_tools
            ]

            step = {
                "type": "capability",
                "step": step_number,
                "capability": capability,
                "status": "resolved" if resolved else "unavailable",
                "tools": resolved,
                "reason": str(action.get("reason", "")),
            }
            steps.append(step)

            if not resolved:
                text = (
                    "Required runtime capability '"
                    + capability
                    + "' is not currently enabled."
                )
                _store_assistant_message(db, project.id, text)
                return {
                    "status": "waiting_capability",
                    "text": text,
                    "steps": steps,
                }

            messages.append({"role": "assistant", "content": raw})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "CAPABILITY RESOLVED: "
                        + capability
                        + " is available through "
                        + ", ".join(resolved)
                        + ". Use the available runtime tool and continue."
                    ),
                }
            )
            continue

        if kind == "delegate_agent":
            agent_id = str(action.get("agent_id", ""))
            if agent_id not in worker_ids:
                result = {
                    "status": "error",
                    "error": "Unknown worker agent",
                }
            else:
                agent = db.get(AgentRecord, agent_id)
                agent.state = "assigned"
                db.commit()
                events.emit(
                    "agent.delegated",
                    agent_id=agent.id,
                    agent_name=agent.name,
                    agent_role=agent.role,
                    project_id=project.id,
                    task=str(action.get("task", message))[:500],
                    state="assigned",
                )
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

            step = {
                "type": kind,
                "step": step_number,
                "agent_id": agent_id,
                "result": result,
            }
            steps.append(step)

        elif kind == "delegate_peers":
            agent_ids = [
                str(item)
                for item in action.get("agent_ids", [])
                if str(item) in worker_ids
            ]

            if len(set(agent_ids)) < 2:
                result = {
                    "status": "error",
                    "error": "At least two valid peers required",
                }
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

                for position, agent_id in enumerate(
                    dict.fromkeys(agent_ids)
                ):
                    db.add(
                        MultiAgentParticipantRecord(
                            task_id=task.id,
                            agent_id=agent_id,
                            position=position,
                            status="ready",
                            last_round=0,
                        )
                    )
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
                    "messages": [
                        item.content
                        for item in finals[-6:]
                    ],
                }

            step = {
                "type": kind,
                "step": step_number,
                "agent_ids": agent_ids,
                "result": result,
            }
            steps.append(step)

        elif kind == "run_workflow":
            workflow_id = str(action.get("workflow_id", ""))

            if workflow_id not in workflow_ids:
                result = {
                    "status": "error",
                    "error": "Unknown workflow",
                }
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

            step = {
                "type": kind,
                "step": step_number,
                "workflow_id": workflow_id,
                "result": result,
            }
            steps.append(step)

        else:
            step = {
                "type": "error",
                "step": step_number,
                "result": {
                    "error": (
                        "Unknown executive action: " + kind
                    )
                },
            }
            steps.append(step)

        messages.append({"role": "assistant", "content": raw})
        messages.append(
            {
                "role": "user",
                "content": (
                    "DELEGATION RESULT:\n"
                    + json.dumps(
                        step,
                        ensure_ascii=False,
                        default=str,
                    )
                    + "\nReassess the overall objective. Use direct tools, "
                    "delegate again, or reply only when the objective is "
                    "complete."
                ),
            }
        )

    text = (
        "Executive safety ceiling reached before the overall task "
        "completed."
    )
    _store_assistant_message(db, project.id, text)
    return {
        "status": "step_limit",
        "text": text,
        "steps": steps,
    }
