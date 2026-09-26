import json
from typing import Any

from app.agents.runner import run_messages
from app.agents.protocol import special_action
from app.core.permissions import ApprovalRequired, Permission
from app.events.bus import events
from app.tools.capabilities import (
    detect_missing_capability,
    resolve_capability,
)
from app.tools.registry import catalog_for_prompt, tools
from app.tools.service import allowed_tool_names

MAX_TURNS = 30

VALIDATION_ROLES = ("tester", "test", "qa", "validator", "validation")


def _working_state(agent) -> str:
    role = str(getattr(agent, "role", "")).lower()
    if any(token in role for token in VALIDATION_ROLES):
        return "validating"
    return "working"


def _set_agent_state(
    *,
    agent,
    db,
    project_id: str,
    state: str,
    **payload: object,
) -> None:
    agent.state = state
    db.commit()
    events.emit(
        "agent.state.changed",
        agent_id=agent.id,
        project_id=project_id,
        state=state,
        **payload,
    )


SYSTEM_PROMPT = """You are an autonomous worker inside Agent Man.
Your job is to keep working until the user's objective is actually complete,
or until the runtime requires an explicit permission that has not been granted.

You may only act through the tools listed below. All file paths must be relative
to the current project workspace. Never invent tool results.

Available tools:
{tools}

Return exactly one JSON object and no markdown.

Use a tool:
{{"type":"tool","tool":"read_file","args":{{"path":"README.md"}}}}

If you need a capability that is not currently usable, request it instead of
stopping or saying you cannot do the task:
{{"type":"capability_request","capability":"internet","reason":"Need current documentation."}}

When you believe the job is finished:
{{"type":"final","verified":true,"message":"What was completed and how it was verified."}}

Rules:
- Do not stop just because the first approach failed. Inspect the error and try
  another safe approach when one is available.
- Do not say you lack internet/web access if an internet tool is available.
  Use it. If a required capability is missing, emit capability_request.
- Do not declare completion until you have checked the requested result.
- A first final answer is treated as a completion candidate. The runtime will
  ask you to review it once more before the task is accepted as complete.
- Never bypass approval requirements.
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
        action = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            try:
                action = json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                action = {"type": "message", "message": raw}
        else:
            action = {"type": "message", "message": raw}

    if not isinstance(action, dict):
        action = {"type": "message", "message": raw}

    text = str(
        action.get("message")
        or action.get("content")
        or raw
    )
    missing = detect_missing_capability(text)
    if missing:
        return {
            "type": "capability_request",
            "capability": missing,
            "reason": text,
        }
    return action


def execute_agent(
    *,
    agent,
    project,
    prompt: str,
    db,
    endpoint: str | None = None,
    allow_terminal: bool = False,
    allow_delete: bool = False,
    allow_network: bool = False,
    allow_hardware: bool = False,
) -> dict[str, Any]:
    approvals: set[str] = set()
    if allow_terminal:
        approvals.add(Permission.TERMINAL_EXECUTE.value)
    if allow_delete:
        approvals.add(Permission.PROJECT_DELETE.value)
    if allow_network:
        approvals.add(Permission.NETWORK_ACCESS.value)
    if allow_hardware:
        approvals.add(Permission.SERIAL_ACCESS.value)

    allowed_names = allowed_tool_names(db, agent.id)
    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT.format(
                tools=catalog_for_prompt(allowed_names)
            ),
        },
        {"role": "user", "content": prompt},
    ]
    trace: list[dict[str, Any]] = []
    verification_pending = False

    _set_agent_state(
        agent=agent,
        db=db,
        project_id=project.id,
        state=_working_state(agent),
        source="run",
    )
    events.emit(
        "agent.run.started",
        agent_id=agent.id,
        project_id=project.id,
        prompt=prompt[:500],
    )

    for turn_number in range(1, MAX_TURNS + 1):
        try:
            raw = run_messages(agent, messages, endpoint)
        except Exception:
            _set_agent_state(
                agent=agent,
                db=db,
                project_id=project.id,
                state="failed",
                source="llm",
            )
            raise
        action = _parse_action(raw)
        action_type = str(action.get("type", "message")).lower()

        if action_type == "capability_request":
            capability = str(action.get("capability", "")).strip().lower()
            resolved = resolve_capability(
                db,
                agent.id,
                capability,
            )
            allowed_names = allowed_tool_names(db, agent.id)

            step = {
                "turn": turn_number,
                "type": "capability",
                "capability": capability,
                "status": "resolved" if resolved else "unavailable",
                "tools": resolved,
                "reason": str(action.get("reason", "")),
            }
            trace.append(step)

            if not resolved:
                _set_agent_state(
                    agent=agent,
                    db=db,
                    project_id=project.id,
                    state="waiting_capability",
                    source="capability",
                    capability=capability,
                )
                events.emit(
                    "agent.capability.unavailable",
                    agent_id=agent.id,
                    project_id=project.id,
                    capability=capability,
                )
                return {
                    "text": (
                        f"No runtime capability is currently available for "
                        f"'{capability}'."
                    ),
                    "steps": trace,
                    "status": "waiting_capability",
                }

            events.emit(
                "agent.capability.resolved",
                agent_id=agent.id,
                project_id=project.id,
                capability=capability,
                tools=resolved,
            )
            messages.append({"role": "assistant", "content": raw})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "CAPABILITY RESOLVED: "
                        + capability
                        + " is available through: "
                        + ", ".join(resolved)
                        + ". Continue the original task. Use the capability "
                        "instead of stopping."
                    ),
                }
            )
            continue

        if action_type == "final":
            message = str(
                action.get("message")
                or action.get("content")
                or raw
            ).strip()

            if not verification_pending:
                verification_pending = True
                _set_agent_state(
                    agent=agent,
                    db=db,
                    project_id=project.id,
                    state="verifying",
                    source="completion_review",
                )
                trace.append(
                    {
                        "turn": turn_number,
                        "type": "completion_candidate",
                        "status": "review_required",
                        "message": message,
                    }
                )
                messages.append({"role": "assistant", "content": raw})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "COMPLETION REVIEW REQUIRED. Re-check the original "
                            "objective, inspect or test the result where possible, "
                            "and review any unresolved tool errors. If more work "
                            "is needed, continue using tools. If the task is truly "
                            "complete, return another final JSON object with "
                            '"verified": true.'
                        ),
                    }
                )
                continue

            if action.get("verified") is not True:
                messages.append({"role": "assistant", "content": raw})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "The completion review is not verified yet. "
                            "Continue checking the work or return final with "
                            '"verified": true only after verification.'
                        ),
                    }
                )
                continue

            _set_agent_state(
                agent=agent,
                db=db,
                project_id=project.id,
                state="completed",
                source="run",
            )
            events.emit(
                "agent.run.completed",
                agent_id=agent.id,
                project_id=project.id,
                turns=turn_number,
                steps=len(trace),
            )
            return {
                "text": message,
                "steps": trace,
                "status": "completed",
            }

        if action_type != "tool":
            messages.append({"role": "assistant", "content": raw})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Continue working on the original objective. "
                        "Use tools when needed. Do not stop with a general "
                        "explanation; finish and verify the actual job."
                    ),
                }
            )
            continue

        if verification_pending:
            _set_agent_state(
                agent=agent,
                db=db,
                project_id=project.id,
                state=_working_state(agent),
                source="run",
            )
        verification_pending = False
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
            step = {
                "turn": turn_number,
                "tool": tool_name,
                "arguments": arguments,
                "status": "ok",
                "result": result,
            }
        except ApprovalRequired as exc:
            step = {
                "turn": turn_number,
                "tool": tool_name,
                "arguments": arguments,
                "status": "approval_required",
                "permission": exc.permission.value,
            }
            trace.append(step)
            _set_agent_state(
                agent=agent,
                db=db,
                project_id=project.id,
                state="waiting_approval",
                source="permission",
                permission=exc.permission.value,
            )
            events.emit(
                "tool.approval_required",
                agent_id=agent.id,
                project_id=project.id,
                tool=tool_name,
                permission=exc.permission.value,
            )
            return {
                "text": (
                    f"{agent.name} can continue automatically after approval "
                    f"for {exc.permission.value}."
                ),
                "steps": trace,
                "status": "waiting_approval",
            }
        except Exception as exc:
            step = {
                "turn": turn_number,
                "tool": tool_name,
                "arguments": arguments,
                "status": "error",
                "error": str(exc),
            }

        trace.append(step)
        events.emit(
            "tool.executed",
            agent_id=agent.id,
            project_id=project.id,
            tool=tool_name,
            status=step["status"],
        )
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
                    + "\nContinue the original task. If this approach failed, "
                    "inspect the failure and try another safe approach."
                ),
            }
        )

    _set_agent_state(
        agent=agent,
        db=db,
        project_id=project.id,
        state="attention",
        source="turn_limit",
    )
    events.emit(
        "agent.run.stopped",
        agent_id=agent.id,
        project_id=project.id,
        reason="turn_limit",
    )
    return {
        "text": (
            f"Stopped at the autonomous safety ceiling of {MAX_TURNS} turns. "
            "The task did not reach verified completion."
        ),
        "steps": trace,
        "status": "turn_limit",
    }
