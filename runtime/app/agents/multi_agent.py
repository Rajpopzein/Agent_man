import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.runner import run_messages
from app.core.permissions import ApprovalRequired, Permission
from app.events.bus import events
from app.persistence.models import (
    AgentRecord,
    MultiAgentMessageRecord,
    MultiAgentParticipantRecord,
    MultiAgentTaskRecord,
    ProjectRecord,
)
from app.providers.connections import bind_agent_connection
from app.tools.registry import catalog_for_prompt, tools
from app.tools.service import allowed_tool_names

MAX_TOOL_STEPS_PER_TURN = 4
MAX_TRANSCRIPT_MESSAGES = 60

SYSTEM_PROMPT = """You are one peer in an Agent Man multi-agent task.
There is no coordinator or lead agent. Work from your own configured role,
reason independently, and use the shared peer discussion to collaborate.

You may use these project tools:
{tools}

All file paths must stay inside the current project workspace. Never invent
tool results. Terminal execution may require explicit user approval.

Return exactly one JSON object and no markdown.

Use a tool:
{{"type":"tool","tool":"read_file","args":{{"path":"README.md"}}}}

Send a contribution to the shared peer discussion:
{{"type":"message","content":"Your useful update, question, review, or proposal."}}

Finish your own contribution:
{{"type":"final","content":"Your final contribution to the task."}}

Do not select a winner or pretend to coordinate the other agents.
"""


def _parse_action(raw: str) -> dict[str, Any]:
    cleaned = raw.strip()
    fence = chr(96) * 3
    if cleaned.startswith(fence):
        cleaned = cleaned.replace(fence + "json", "", 1).replace(fence, "", 1).strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            try:
                parsed = json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                parsed = {"type": "message", "content": raw}
        else:
            parsed = {"type": "message", "content": raw}
    if not isinstance(parsed, dict):
        return {"type": "message", "content": raw}
    return parsed


def _transcript(db: Session, task_id: str) -> list[MultiAgentMessageRecord]:
    return list(
        db.scalars(
            select(MultiAgentMessageRecord)
            .where(MultiAgentMessageRecord.task_id == task_id)
            .order_by(MultiAgentMessageRecord.created_at)
        ).all()
    )[-MAX_TRANSCRIPT_MESSAGES:]


def _format_transcript(messages, agents: dict[str, AgentRecord]) -> str:
    if not messages:
        return "(No peer messages yet.)"
    lines = []
    for message in messages:
        agent = agents.get(message.agent_id) if message.agent_id else None
        author = agent.name if agent else "Runtime"
        lines.append(
            f"[round {message.round_number}] {author} / {message.kind}: {message.content}"
        )
    return "\n".join(lines)


def _run_peer_turn(*, agent, project, task, round_number, db, agents, approvals):
    allowed_names = allowed_tool_names(db, agent.id)
    transcript = _format_transcript(_transcript(db, task.id), agents)
    peers = ", ".join(
        f"{peer.name} ({peer.role})"
        for peer in agents.values()
        if peer.id != agent.id
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT.format(tools=catalog_for_prompt(allowed_names))},
        {
            "role": "user",
            "content": (
                f"Shared task: {task.prompt}\n"
                f"Your role: {agent.role}\n"
                f"Peer agents: {peers or '(none)'}\n"
                f"Current round: {round_number} of {task.max_rounds}\n\n"
                f"Shared discussion:\n{transcript}\n\n"
                "Take one useful peer turn now."
            ),
        },
    ]

    for step in range(1, MAX_TOOL_STEPS_PER_TURN + 1):
        raw = run_messages(agent, messages)
        action = _parse_action(raw)
        action_type = str(action.get("type", "message"))

        if action_type in {"message", "final"}:
            content = str(action.get("content") or action.get("message") or raw).strip()
            return {"type": action_type, "content": content, "tool_steps": step - 1}

        if action_type != "tool":
            return {"type": "message", "content": raw.strip(), "tool_steps": step - 1}

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
            tool_result = {"tool": tool_name, "status": "ok", "result": result}
            events.emit(
                "multi_agent.tool.executed",
                task_id=task.id,
                agent_id=agent.id,
                tool=tool_name,
                status="ok",
            )
        except ApprovalRequired as exc:
            return {
                "type": "approval_required",
                "permission": exc.permission.value,
                "tool": tool_name,
                "arguments": arguments,
            }
        except Exception as exc:
            tool_result = {"tool": tool_name, "status": "error", "error": str(exc)}
            events.emit(
                "multi_agent.tool.executed",
                task_id=task.id,
                agent_id=agent.id,
                tool=tool_name,
                status="error",
            )

        messages.append({"role": "assistant", "content": raw})
        messages.append(
            {
                "role": "user",
                "content": (
                    "TOOL RESULT:\n"
                    + json.dumps(tool_result, ensure_ascii=False, default=str)
                    + "\nContinue this same peer turn. Use another tool, "
                    "send a peer message, or finish your contribution."
                ),
            }
        )

    return {
        "type": "message",
        "content": (
            f"{agent.name} reached the per-turn tool limit and will "
            "continue in the next round."
        ),
        "tool_steps": MAX_TOOL_STEPS_PER_TURN,
    }


def run_peer_task(*, task, db: Session, allow_terminal: bool = False, allow_delete: bool = False):
    project = db.get(ProjectRecord, task.project_id)
    if project is None:
        raise ValueError("Project not found")

    participants = list(
        db.scalars(
            select(MultiAgentParticipantRecord)
            .where(MultiAgentParticipantRecord.task_id == task.id)
            .order_by(MultiAgentParticipantRecord.position)
        ).all()
    )
    agents = {}
    for participant in participants:
        agent = db.get(AgentRecord, participant.agent_id)
        if agent is None:
            participant.status = "failed"
            continue
        bind_agent_connection(agent, db)
        agents[agent.id] = agent

    approvals = set()
    if allow_terminal:
        approvals.add(Permission.TERMINAL_EXECUTE.value)
    if allow_delete:
        approvals.add(Permission.PROJECT_DELETE.value)

    if task.status in {"completed", "completed_with_errors", "round_limit"}:
        return task

    task.status = "executing"
    start_round = task.current_round or 1
    events.emit(
        "multi_agent.task.started",
        task_id=task.id,
        project_id=task.project_id,
        participants=len(participants),
    )

    for round_number in range(start_round, task.max_rounds + 1):
        task.current_round = round_number
        db.commit()

        for participant in participants:
            if participant.status in {"completed", "failed"}:
                continue
            if participant.last_round >= round_number:
                continue

            agent = agents.get(participant.agent_id)
            if agent is None:
                participant.status = "failed"
                participant.last_round = round_number
                db.commit()
                continue

            participant.status = "running"
            agent.state = "thinking"
            db.commit()

            try:
                result = _run_peer_turn(
                    agent=agent,
                    project=project,
                    task=task,
                    round_number=round_number,
                    db=db,
                    agents=agents,
                    approvals=approvals,
                )
            except Exception as exc:
                participant.status = "failed"
                participant.last_round = round_number
                agent.state = "idle"
                db.add(
                    MultiAgentMessageRecord(
                        task_id=task.id,
                        agent_id=agent.id,
                        kind="error",
                        round_number=round_number,
                        content=str(exc),
                    )
                )
                db.commit()
                events.emit(
                    "multi_agent.agent.failed",
                    task_id=task.id,
                    agent_id=agent.id,
                    error=str(exc)[:500],
                )
                continue

            if result["type"] == "approval_required":
                participant.status = "waiting_approval"
                agent.state = "waiting"
                task.status = "waiting_approval"
                db.commit()
                events.emit(
                    "multi_agent.approval_required",
                    task_id=task.id,
                    agent_id=agent.id,
                    permission=result["permission"],
                    tool=result["tool"],
                )
                return task

            kind = "final" if result["type"] == "final" else "message"
            db.add(
                MultiAgentMessageRecord(
                    task_id=task.id,
                    agent_id=agent.id,
                    kind=kind,
                    round_number=round_number,
                    content=str(result["content"]).strip(),
                )
            )
            participant.last_round = round_number
            participant.status = "completed" if kind == "final" else "active"
            agent.state = "idle"
            db.commit()
            events.emit(
                "multi_agent.message",
                task_id=task.id,
                agent_id=agent.id,
                kind=kind,
                round=round_number,
            )

        active = [
            participant
            for participant in participants
            if participant.status not in {"completed", "failed"}
        ]
        if not active:
            failed = any(p.status == "failed" for p in participants)
            task.status = "completed_with_errors" if failed else "completed"
            task.completed_at = datetime.now(timezone.utc)
            db.commit()
            events.emit(
                "multi_agent.task.completed",
                task_id=task.id,
                status=task.status,
            )
            return task

    task.status = "round_limit"
    task.completed_at = datetime.now(timezone.utc)
    for participant in participants:
        if participant.status not in {"completed", "failed"}:
            participant.status = "round_limit"
        agent = agents.get(participant.agent_id)
        if agent is not None:
            agent.state = "idle"
    db.commit()
    events.emit(
        "multi_agent.task.completed",
        task_id=task.id,
        status=task.status,
    )
    return task
