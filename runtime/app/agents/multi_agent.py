import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.runner import run_messages
from app.agents.protocol import special_action
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
from app.tools.capabilities import (
    detect_missing_capability,
    resolve_capability,
)
from app.tools.registry import catalog_for_prompt, tools
from app.tools.service import allowed_tool_names

MAX_TOOL_STEPS_PER_TURN = 4
MAX_TRANSCRIPT_MESSAGES = 120
STABLE_COMPLETION_ROUNDS = 2

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

If you need a capability, request it instead of giving up:
{{"type":"capability_request","capability":"internet","reason":"Need current public documentation."}}

Continue collaboration:
{{"type":"message","content":"A useful update, question, finding, review, or requested change."}}

Declare the overall task complete from your role:
{{"type":"final","content":"Why the shared job is complete from your role and any final result."}}

Important completion rule:
- Do not return final merely because your own small part is done.
- Review the latest peer discussion and project state.
- If another peer still has work, raised an issue, changed the implementation,
  or needs your review, return message and keep collaborating.
- Return final only when you believe the shared objective is complete from your
  role and there are no unresolved issues you can identify.
- The runtime requires all healthy peers to independently confirm completion
  across stable rounds before the task can finish.
- Do not say you lack internet/web access if an internet tool is available.
  Use it. If a capability is missing, return capability_request.

Do not select a winner or pretend to coordinate the other agents.
"""


def _parse_action(raw: str) -> dict[str, Any]:
    special = special_action(raw)
    if special is not None:
        return special
    cleaned = raw.strip()
    fence = chr(96) * 3
    if cleaned.startswith(fence):
        cleaned = (
            cleaned.replace(fence + "json", "", 1)
            .replace(fence, "", 1)
            .strip()
        )
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


def _transcript(
    db: Session,
    task_id: str,
) -> list[MultiAgentMessageRecord]:
    return list(
        db.scalars(
            select(MultiAgentMessageRecord)
            .where(MultiAgentMessageRecord.task_id == task_id)
            .order_by(MultiAgentMessageRecord.created_at)
        ).all()
    )[-MAX_TRANSCRIPT_MESSAGES:]


def _format_transcript(
    messages: list[MultiAgentMessageRecord],
    agents: dict[str, AgentRecord],
) -> str:
    if not messages:
        return "(No peer messages yet.)"
    lines = []
    for message in messages:
        agent = (
            agents.get(message.agent_id)
            if message.agent_id
            else None
        )
        author = agent.name if agent else "Runtime"
        lines.append(
            f"[round {message.round_number}] "
            f"{author} / {message.kind}: {message.content}"
        )
    return "\n".join(lines)


def _round_all_final(
    db: Session,
    task_id: str,
    round_number: int,
    participant_ids: set[str],
) -> bool:
    if not participant_ids or round_number < 1:
        return False

    messages = db.scalars(
        select(MultiAgentMessageRecord).where(
            MultiAgentMessageRecord.task_id == task_id,
            MultiAgentMessageRecord.round_number == round_number,
            MultiAgentMessageRecord.agent_id.in_(participant_ids),
        )
    ).all()

    latest_kind: dict[str, str] = {}
    for message in messages:
        if message.agent_id:
            latest_kind[message.agent_id] = message.kind

    return (
        set(latest_kind) == participant_ids
        and all(
            latest_kind[agent_id] == "final"
            for agent_id in participant_ids
        )
    )


def _run_peer_turn(
    *,
    agent: AgentRecord,
    project: ProjectRecord,
    task: MultiAgentTaskRecord,
    round_number: int,
    db: Session,
    agents: dict[str, AgentRecord],
    approvals: set[str],
) -> dict[str, Any]:
    allowed_names = allowed_tool_names(db, agent.id)
    transcript = _format_transcript(
        _transcript(db, task.id),
        agents,
    )
    peers = ", ".join(
        f"{peer.name} ({peer.role})"
        for peer in agents.values()
        if peer.id != agent.id
    )
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
                f"Shared task: {task.prompt}\n"
                f"Your role: {agent.role}\n"
                f"Peer agents: {peers or '(none)'}\n"
                f"Current collaboration round: "
                f"{round_number} of safety ceiling "
                f"{task.max_rounds}\n\n"
                f"Shared discussion:\n{transcript}\n\n"
                "Take one useful peer turn now. Inspect the project "
                "with tools when that is needed to verify the shared job."
            ),
        },
    ]

    for step in range(1, MAX_TOOL_STEPS_PER_TURN + 1):
        raw = run_messages(agent, messages)
        action = _parse_action(raw)
        action_type = str(
            action.get("type", "message")
        ).lower()
        action_text = str(
            action.get("content")
            or action.get("message")
            or raw
        )
        missing = detect_missing_capability(action_text)
        if missing:
            action = {
                "type": "capability_request",
                "capability": missing,
                "reason": action_text,
            }
            action_type = "capability_request"

        if action_type == "capability_request":
            capability = str(
                action.get("capability", "")
            ).strip().lower()
            resolved = resolve_capability(
                db,
                agent.id,
                capability,
            )
            allowed_names = allowed_tool_names(
                db,
                agent.id,
            )
            if not resolved:
                return {
                    "type": "message",
                    "content": (
                        f"Runtime capability '{capability}' is unavailable. "
                        "Another peer may continue if it has a viable approach."
                    ),
                    "tool_steps": step - 1,
                }
            events.emit(
                "multi_agent.capability.resolved",
                task_id=task.id,
                agent_id=agent.id,
                capability=capability,
                tools=resolved,
            )
            messages.append(
                {"role": "assistant", "content": raw}
            )
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "CAPABILITY RESOLVED: "
                        + capability
                        + " is available through: "
                        + ", ".join(resolved)
                        + ". Continue this peer turn and use it."
                    ),
                }
            )
            continue

        if action_type in {"message", "final"}:
            content = str(
                action.get("content")
                or action.get("message")
                or raw
            ).strip()
            return {
                "type": action_type,
                "content": content,
                "tool_steps": step - 1,
            }

        if action_type != "tool":
            messages.extend([
                {"role": "assistant", "content": raw},
                {"role": "user", "content": "Invalid action. Return one valid JSON tool, message, or final action; do not print tool-call markers."},
            ])
            continue

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
            tool_result = {
                "tool": tool_name,
                "status": "error",
                "error": str(exc),
            }
            events.emit(
                "multi_agent.tool.executed",
                task_id=task.id,
                agent_id=agent.id,
                tool=tool_name,
                status="error",
            )

        messages.append(
            {"role": "assistant", "content": raw}
        )
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
                    + "\nContinue this same peer turn. "
                    "Use another tool, send a peer message, "
                    "or confirm final only if the shared job "
                    "is actually complete."
                ),
            }
        )

    return {
        "type": "message",
        "content": (
            f"{agent.name} reached the per-turn tool limit and will "
            "continue in the next collaboration round."
        ),
        "tool_steps": MAX_TOOL_STEPS_PER_TURN,
    }


def run_peer_task(
    *,
    task: MultiAgentTaskRecord,
    db: Session,
    allow_terminal: bool = False,
    allow_delete: bool = False,
    allow_network: bool = False,
    allow_hardware: bool = False,
) -> MultiAgentTaskRecord:
    project = db.get(
        ProjectRecord,
        task.project_id,
    )
    if project is None:
        raise ValueError("Project not found")

    participants = list(
        db.scalars(
            select(MultiAgentParticipantRecord)
            .where(
                MultiAgentParticipantRecord.task_id
                == task.id
            )
            .order_by(
                MultiAgentParticipantRecord.position
            )
        ).all()
    )

    agents: dict[str, AgentRecord] = {}
    for participant in participants:
        agent = db.get(
            AgentRecord,
            participant.agent_id,
        )
        if agent is None:
            participant.status = "failed"
            continue
        bind_agent_connection(agent, db)
        agents[agent.id] = agent

    approvals: set[str] = set()
    if allow_terminal:
        approvals.add(
            Permission.TERMINAL_EXECUTE.value
        )
    if allow_delete:
        approvals.add(
            Permission.PROJECT_DELETE.value
        )
    if allow_network:
        approvals.add(
            Permission.NETWORK_ACCESS.value
        )
    if allow_hardware:
        approvals.add(
            Permission.SERIAL_ACCESS.value
        )

    if task.status in {
        "completed",
        "completed_with_errors",
        "failed",
    }:
        return task

    original_status = task.status
    task.status = "executing"
    task.completed_at = None
    db.commit()

    if (
        original_status == "waiting_approval"
        and task.current_round > 0
    ):
        start_round = task.current_round
    elif task.current_round > 0:
        start_round = task.current_round + 1
    else:
        start_round = 1

    events.emit(
        "multi_agent.task.started",
        task_id=task.id,
        project_id=task.project_id,
        participants=len(participants),
        start_round=start_round,
        max_rounds=task.max_rounds,
    )

    for round_number in range(
        start_round,
        task.max_rounds + 1,
    ):
        task.current_round = round_number
        db.commit()

        for participant in participants:
            if participant.status == "failed":
                continue
            if participant.last_round >= round_number:
                continue

            agent = agents.get(
                participant.agent_id
            )
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

            if (
                result["type"]
                == "approval_required"
            ):
                participant.status = (
                    "waiting_approval"
                )
                agent.state = "waiting"
                task.status = "waiting_approval"
                db.commit()
                events.emit(
                    "multi_agent.approval_required",
                    task_id=task.id,
                    agent_id=agent.id,
                    permission=result[
                        "permission"
                    ],
                    tool=result["tool"],
                )
                return task

            kind = (
                "final"
                if result["type"] == "final"
                else "message"
            )
            db.add(
                MultiAgentMessageRecord(
                    task_id=task.id,
                    agent_id=agent.id,
                    kind=kind,
                    round_number=round_number,
                    content=str(
                        result["content"]
                    ).strip(),
                )
            )
            participant.last_round = round_number
            participant.status = (
                "ready_for_completion"
                if kind == "final"
                else "active"
            )
            agent.state = "idle"
            db.commit()

            events.emit(
                "multi_agent.message",
                task_id=task.id,
                agent_id=agent.id,
                kind=kind,
                round=round_number,
            )

        healthy_ids = {
            participant.agent_id
            for participant in participants
            if participant.status != "failed"
        }

        if not healthy_ids:
            task.status = "failed"
            task.completed_at = (
                datetime.now(timezone.utc)
            )
            db.commit()
            return task

        current_all_final = _round_all_final(
            db,
            task.id,
            round_number,
            healthy_ids,
        )
        previous_all_final = _round_all_final(
            db,
            task.id,
            round_number - 1,
            healthy_ids,
        )

        if (
            current_all_final
            and previous_all_final
        ):
            failed = any(
                participant.status == "failed"
                for participant in participants
            )
            for participant in participants:
                if participant.status != "failed":
                    participant.status = "completed"
            task.status = (
                "completed_with_errors"
                if failed
                else "completed"
            )
            task.completed_at = (
                datetime.now(timezone.utc)
            )
            db.commit()
            events.emit(
                "multi_agent.task.completed",
                task_id=task.id,
                status=task.status,
                stable_rounds=STABLE_COMPLETION_ROUNDS,
            )
            return task

        for participant in participants:
            if (
                participant.status
                == "ready_for_completion"
            ):
                participant.status = "reviewing"
        db.commit()

        events.emit(
            "multi_agent.round.completed",
            task_id=task.id,
            round=round_number,
            all_final=current_all_final,
            stable=(
                current_all_final
                and previous_all_final
            ),
        )

    task.status = "round_limit"
    task.completed_at = datetime.now(timezone.utc)
    for participant in participants:
        if participant.status != "failed":
            participant.status = "round_limit"
        agent = agents.get(
            participant.agent_id
        )
        if agent is not None:
            agent.state = "idle"
    db.commit()

    events.emit(
        "multi_agent.task.paused",
        task_id=task.id,
        status=task.status,
        reason="safety_ceiling",
    )
    return task
