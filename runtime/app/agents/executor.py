import json
from typing import Any, Callable

from app.agents.runner import run_messages
from app.agents.protocol import special_action
from app.core.permissions import ApprovalRequired, Permission
from app.events.bus import events
from app.tools.capabilities import (
    detect_missing_capability,
    resolve_capability,
)
from app.tools.intelligence import recovery_guidance
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
        agent_name=agent.name,
        agent_role=agent.role,
        project_id=project_id,
        state=state,
        **payload,
    )


def _report_progress(
    callback: Callable[[dict[str, Any]], None] | None,
    *,
    phase: str,
    action: str,
    tool: str = "",
    detail: str = "",
    status: str = "running",
) -> None:
    if callback is None:
        return
    callback(
        {
            "phase": phase,
            "action": action[:500],
            "tool": tool[:160],
            "detail": detail[:2000],
            "status": status,
        }
    )


SYSTEM_PROMPT = """You are an autonomous worker inside Agent Man.
Your job is to keep working until the user's objective is actually complete,
or until the runtime requires an explicit permission that has not been granted.

You may only act through the tools listed below. All file paths must be relative
to the current project workspace. Never invent tool results.

AGENT ROLE:
{agent_role}

AGENT CONTEXT:
{agent_context}

The agent context defines your responsibilities, scope, and operating behavior.
It does not grant permissions or tools; only the runtime tool list below does.

Available tools:
{tools}

Return exactly one JSON object and no markdown.

Use a tool:
{{"type":"tool","tool":"read_file","args":{{"path":"README.md"}},"progress":"Reading the project overview before making changes."}}

If you need a capability that is not currently usable, request it instead of
stopping or saying you cannot do the task:
{{"type":"capability_request","capability":"internet","reason":"Need current documentation."}}

When you believe the job is finished:
{{"type":"final","verified":true,"message":"What was completed and how it was verified."}}

Rules:
- Every tool, capability, or completion action should include a short
  "progress" field written for the user. It must say what you are doing now
  and the immediate purpose in one simple sentence. Do not expose private
  chain-of-thought, hidden analysis, secrets, or long reasoning.
- Do not stop just because the first approach failed. Inspect the error and try
  another safe approach when one is available.
- Do not say you lack internet/web access if an internet tool is available.
  Use it. If a required capability is missing, emit capability_request.
- Do not declare completion until you have checked the requested result.
- A first final answer is treated as a completion candidate. The runtime will
  ask you to review it once more before the task is accepted as complete.
- Never bypass approval requirements.
- Responce by the way human understand do not speak special charecters
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
    progress: Callable[[dict[str, Any]], None] | None = None,
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
                agent_role=str(getattr(agent, "role", "")) or "(unspecified)",
                agent_context=(
                    str(getattr(agent, "context", "")).strip()
                    or "(no custom context provided)"
                ),
                tools=catalog_for_prompt(allowed_names),
            ),
        },
        {"role": "user", "content": prompt},
    ]
    trace: list[dict[str, Any]] = []
    verification_pending = False
    correction_count = 0
    active_correction: dict[str, Any] | None = None

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
    _report_progress(
        progress,
        phase="starting",
        action="Started the assigned task.",
        detail=prompt,
    )

    for turn_number in range(1, MAX_TURNS + 1):
        _report_progress(
            progress,
            phase="planning",
            action="Planning the next action.",
            detail=f"Turn {turn_number}",
        )
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
        progress_note = " ".join(
            str(action.get("progress", "")).split()
        )[:500]

        if action_type == "capability_request":
            capability = str(action.get("capability", "")).strip().lower()
            _report_progress(
                progress,
                phase="capability",
                action=(
                    progress_note
                    or "Checking a required capability."
                ),
                detail=capability,
            )
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
                _report_progress(
                    progress,
                    phase="waiting_capability",
                    action="Waiting for a required capability.",
                    detail=capability,
                    status="waiting_capability",
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
                _report_progress(
                    progress,
                    phase="verifying",
                    action=(
                        progress_note
                        or "Checking the completed work before finishing."
                    ),
                    detail=message,
                )
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
            _report_progress(
                progress,
                phase="completed",
                action="Finished and verified the assigned task.",
                detail=message,
                status="completed",
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

        _report_progress(
            progress,
            phase="tool",
            action=(
                progress_note
                or "Using " + tool_name + "."
            ),
            tool=tool_name,
            detail=json.dumps(
                arguments,
                ensure_ascii=False,
                default=str,
            ),
        )

        try:
            result = tools.execute(
                name=tool_name,
                arguments=arguments,
                workspace_path=project.workspace_path,
                project_id=project.id,
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
            _report_progress(
                progress,
                phase="tool_result",
                action=tool_name + " completed.",
                tool=tool_name,
                detail=json.dumps(
                    result,
                    ensure_ascii=False,
                    default=str,
                ),
            )
            if tool_name in {
                "run_command",
                "run_tests",
                "run_build",
                "lint",
                "read_process_output",
            }:
                events.emit(
                    "runtime.console",
                    agent_id=agent.id,
                    agent_name=agent.name,
                    agent_role=agent.role,
                    project_id=project.id,
                    source=tool_name,
                    status="ok",
                    message=json.dumps(
                        result,
                        ensure_ascii=False,
                        default=str,
                    )[-8000:],
                )
        except ApprovalRequired as exc:
            step = {
                "turn": turn_number,
                "tool": tool_name,
                "arguments": arguments,
                "status": "approval_required",
                "permission": exc.permission.value,
            }
            trace.append(step)
            _report_progress(
                progress,
                phase="waiting_approval",
                action=tool_name + " needs approval.",
                tool=tool_name,
                detail=exc.permission.value,
                status="waiting_approval",
            )
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
                    f"{agent.name} is waiting for approval to use "
                    f"{tool_name}. Required permission: "
                    f"{exc.permission.value}. Approve it in Mission Control, "
                    "then ask Agent Man to retry the worker."
                ),
                "steps": trace,
                "status": "waiting_approval",
            }
        except Exception as exc:
            recovery = recovery_guidance(
                tool_name,
                str(exc),
                allowed_names,
            )
            step = {
                "turn": turn_number,
                "tool": tool_name,
                "arguments": arguments,
                "status": "error",
                "error": str(exc),
                "recovery_tools": list(recovery),
            }

        trace.append(step)

        if step["status"] == "error":
            _report_progress(
                progress,
                phase="recovering",
                action=tool_name + " failed. Trying a safer next step.",
                tool=tool_name,
                detail=str(step.get("error", "")),
                status="error",
            )
            correction_count += 1
            active_correction = {
                "failed_tool": tool_name,
                "error": step["error"],
                "recovery_tools": step.get("recovery_tools", []),
            }
            correction_step = {
                "turn": turn_number,
                "type": "self_correction",
                "status": "replanning",
                "failed_tool": tool_name,
                "error": step["error"],
                "recovery_tools": step.get("recovery_tools", []),
                "correction_number": correction_count,
            }
            trace.append(correction_step)
            events.emit(
                "agent.self_correction",
                agent_id=agent.id,
                agent_name=agent.name,
                project_id=project.id,
                status="replanning",
                failed_tool=tool_name,
                recovery_tools=step.get("recovery_tools", []),
                correction_number=correction_count,
            )
        elif active_correction is not None:
            recovery_step = {
                "turn": turn_number,
                "type": "self_correction",
                "status": "recovered",
                "failed_tool": active_correction["failed_tool"],
                "recovery_tool": tool_name,
            }
            trace.append(recovery_step)
            events.emit(
                "agent.self_correction",
                agent_id=agent.id,
                agent_name=agent.name,
                project_id=project.id,
                status="recovered",
                failed_tool=active_correction["failed_tool"],
                recovery_tool=tool_name,
            )
            active_correction = None

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
                    + (
                        "\nSELF-CORRECTION CHECKPOINT: Re-plan from the "
                        "observable failure and recovery tools. Do not keep "
                        "repeating an unchanged failing action."
                        if step["status"] == "error"
                        else ""
                    )
                    + "\nContinue the original task. If this approach failed, "
                    "revise the plan and try another safe approach."
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
    _report_progress(
        progress,
        phase="attention",
        action="Stopped at the worker safety limit.",
        detail="The task needs another execution turn.",
        status="attention",
    )
    return {
        "text": (
            f"Stopped at the autonomous safety ceiling of {MAX_TURNS} turns. "
            "The task did not reach verified completion."
        ),
        "steps": trace,
        "status": "turn_limit",
    }
