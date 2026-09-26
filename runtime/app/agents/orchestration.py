import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.agents.runner import run_messages
from app.core.permissions import ApprovalRequired, Permission
from app.events.bus import events
from app.persistence.models import (
    AgentRecord,
    ProjectRecord,
    WorkflowNodeRecord,
    WorkflowRecord,
    WorkflowRunRecord,
    WorkflowRunStepRecord,
)
from app.providers.connections import bind_agent_connection
from app.tools.registry import catalog_for_prompt, tools
from app.tools.service import allowed_tool_names

MAX_NODE_TOOL_STEPS = 6
MAX_TRANSITIONS = 25

SYSTEM_PROMPT = """You are executing one stage in an Agent Man workflow.
You are not the coordinator. The runtime owns workflow transitions.

Use only the tools listed below:
{tools}

Return exactly one JSON object and no markdown.

Use a tool:
{{"type":"tool","tool":"read_file","args":{{"path":"README.md"}}}}

Finish this stage:
{{"type":"final","outcome":"success","message":"What you completed."}}

If the stage cannot satisfy its acceptance criteria:
{{"type":"final","outcome":"failure","message":"Why this stage failed."}}

Outcome must be either success or failure. Never choose the next workflow node.
"""


def _parse(raw: str) -> dict[str, Any]:
    cleaned = raw.strip()
    fence = chr(96) * 3
    if cleaned.startswith(fence):
        cleaned = cleaned.replace(fence + "json", "", 1).replace(fence, "", 1).strip()
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            try:
                value = json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                return {
                    "type": "final",
                    "outcome": "failure",
                    "message": raw,
                }
        else:
            return {
                "type": "final",
                "outcome": "failure",
                "message": raw,
            }
    if not isinstance(value, dict):
        return {
            "type": "final",
            "outcome": "failure",
            "message": raw,
        }
    return value


def _execute_node(
    *,
    run: WorkflowRunRecord,
    workflow: WorkflowRecord,
    node: WorkflowNodeRecord,
    agent: AgentRecord,
    project: ProjectRecord,
    db: Session,
    prior_output: str,
    approvals: set[str],
) -> dict[str, Any]:
    allowed_names = allowed_tool_names(db, agent.id)
    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT.format(
                tools=catalog_for_prompt(allowed_names)
            ),
        },
        {
            "role": "user",
            "content": (
                f"Workflow: {workflow.name}\n"
                f"Overall objective: {run.input_prompt}\n"
                f"Stage: {node.name}\n"
                f"Your role: {agent.role}\n"
                f"Stage instructions: {node.instructions}\n\n"
                f"Previous stage output:\n{prior_output or '(none)'}\n\n"
                "Execute only this stage."
            ),
        },
    ]

    for _ in range(MAX_NODE_TOOL_STEPS):
        raw = run_messages(agent, messages)
        action = _parse(raw)

        if action.get("type") == "final":
            outcome = str(action.get("outcome", "failure")).lower()
            if outcome not in {"success", "failure"}:
                outcome = "failure"
            return {
                "status": "completed",
                "outcome": outcome,
                "message": str(
                    action.get("message")
                    or action.get("content")
                    or raw
                ).strip(),
            }

        if action.get("type") != "tool":
            return {
                "status": "completed",
                "outcome": "failure",
                "message": raw.strip(),
            }

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
                allowed_names=allowed_names,
            )
            tool_result = {
                "tool": tool_name,
                "status": "ok",
                "result": result,
            }
        except ApprovalRequired as exc:
            return {
                "status": "waiting_approval",
                "outcome": None,
                "message": (
                    f"Approval required for {exc.permission.value}"
                ),
                "permission": exc.permission.value,
                "tool": tool_name,
            }
        except Exception as exc:
            tool_result = {
                "tool": tool_name,
                "status": "error",
                "error": str(exc),
            }

        events.emit(
            "workflow.tool",
            run_id=run.id,
            node_id=node.id,
            agent_id=agent.id,
            tool=tool_name,
            status=tool_result["status"],
        )
        messages.append({"role": "assistant", "content": raw})
        messages.append(
            {
                "role": "user",
                "content": (
                    "TOOL RESULT:\n"
                    + json.dumps(
                        tool_result,
                        ensure_ascii=False,
                        default=str,
                    )
                    + "\nContinue this stage."
                ),
            }
        )

    return {
        "status": "completed",
        "outcome": "failure",
        "message": "Stage reached the tool-step safety limit.",
    }


def execute_workflow_run(
    *,
    run: WorkflowRunRecord,
    db: Session,
    allow_terminal: bool = False,
    allow_delete: bool = False,
) -> WorkflowRunRecord:
    workflow = db.get(WorkflowRecord, run.workflow_id)
    project = db.get(ProjectRecord, run.project_id)
    if workflow is None or project is None:
        raise ValueError("Workflow or project not found")

    approvals: set[str] = set()
    if allow_terminal:
        approvals.add(Permission.TERMINAL_EXECUTE.value)
    if allow_delete:
        approvals.add(Permission.PROJECT_DELETE.value)

    run.status = "executing"
    db.commit()

    nodes = {
        node.id: node
        for node in workflow_nodes(workflow.id, db)
    }
    current_id = run.current_node_id or workflow.start_node_id
    prior_output = run.last_output or ""

    for _transition in range(MAX_TRANSITIONS):
        if not current_id:
            run.status = "completed"
            run.completed_at = datetime.now(timezone.utc)
            db.commit()
            return run

        node = nodes.get(current_id)
        if node is None:
            run.status = "failed"
            run.last_output = f"Workflow node not found: {current_id}"
            run.completed_at = datetime.now(timezone.utc)
            db.commit()
            return run

        agent = db.get(AgentRecord, node.agent_id)
        if agent is None:
            run.status = "failed"
            run.last_output = f"Agent not found for stage {node.name}"
            run.completed_at = datetime.now(timezone.utc)
            db.commit()
            return run

        bind_agent_connection(agent, db)
        run.current_node_id = node.id
        run.step_count += 1
        agent.state = "executing"
        db.commit()

        attempt = 1
        result = None
        while attempt <= node.max_retries + 1:
            try:
                result = _execute_node(
                    run=run,
                    workflow=workflow,
                    node=node,
                    agent=agent,
                    project=project,
                    db=db,
                    prior_output=prior_output,
                    approvals=approvals,
                )
            except Exception as exc:
                result = {
                    "status": "error",
                    "outcome": None,
                    "message": str(exc),
                }
            if result["status"] != "error":
                break
            attempt += 1

        step = WorkflowRunStepRecord(
            run_id=run.id,
            node_id=node.id,
            agent_id=agent.id,
            attempt=attempt,
            status=result["status"],
            outcome=result.get("outcome"),
            output_text=result.get("message", ""),
        )
        db.add(step)
        run.last_output = result.get("message", "")
        agent.state = "idle"

        if result["status"] == "waiting_approval":
            run.status = "waiting_approval"
            db.commit()
            events.emit(
                "workflow.approval_required",
                run_id=run.id,
                node_id=node.id,
                agent_id=agent.id,
                permission=result.get("permission"),
                tool=result.get("tool"),
            )
            return run

        outcome = result.get("outcome", "failure")
        prior_output = result.get("message", "")
        next_id = (
            node.on_success_node_id
            if outcome == "success"
            else node.on_failure_node_id
        )

        events.emit(
            "workflow.node.completed",
            run_id=run.id,
            node_id=node.id,
            agent_id=agent.id,
            outcome=outcome,
            next_node_id=next_id,
        )

        if next_id is None:
            run.status = (
                "completed"
                if outcome == "success"
                else "failed"
            )
            run.current_node_id = None
            run.completed_at = datetime.now(timezone.utc)
            db.commit()
            return run

        current_id = next_id
        run.current_node_id = current_id
        db.commit()

    run.status = "transition_limit"
    run.completed_at = datetime.now(timezone.utc)
    db.commit()
    return run


def workflow_nodes(
    workflow_id: str,
    db: Session,
) -> list[WorkflowNodeRecord]:
    from sqlalchemy import select

    return list(
        db.scalars(
            select(WorkflowNodeRecord)
            .where(WorkflowNodeRecord.workflow_id == workflow_id)
            .order_by(WorkflowNodeRecord.position)
        ).all()
    )
