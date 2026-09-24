import json
from typing import Any

from app.agents.runner import run_messages
from app.core.permissions import ApprovalRequired, Permission
from app.events.bus import events
from app.tools.registry import catalog_for_prompt, tools

MAX_STEPS = 8

SYSTEM_PROMPT = """You are an autonomous worker inside Agent Man.
You may only act through the tools listed below. All file paths must be relative
to the current project workspace. Never invent tool results.

Available tools:
{tools}

For each turn, return exactly one JSON object and no markdown.

To use a tool:
{{"type":"tool","tool":"read_file","args":{{"path":"README.md"}}}}

To finish:
{{"type":"final","message":"What you completed and anything the user should know."}}

If a tool reports that approval is required, do not bypass it. Explain that
approval is needed in your final response.
"""


def _parse_action(raw: str) -> dict[str, Any]:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.replace("```json", "", 1).replace("```", "", 1).strip()
    try:
        action = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            return {"type": "final", "message": raw}
        try:
            action = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError:
            return {"type": "final", "message": raw}
    if not isinstance(action, dict):
        return {"type": "final", "message": raw}
    return action


def execute_agent(*, agent, project, prompt: str, endpoint: str | None = None, allow_terminal: bool = False) -> dict[str, Any]:
    approvals: set[str] = set()
    if allow_terminal:
        approvals.add(Permission.TERMINAL_EXECUTE.value)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT.format(tools=catalog_for_prompt())},
        {"role": "user", "content": prompt},
    ]
    trace: list[dict[str, Any]] = []

    events.emit("agent.run.started", agent_id=agent.id, project_id=project.id, prompt=prompt[:500])

    for step_number in range(1, MAX_STEPS + 1):
        raw = run_messages(agent, messages, endpoint)
        action = _parse_action(raw)

        if action.get("type") != "tool":
            message = str(action.get("message") or raw)
            events.emit("agent.run.completed", agent_id=agent.id, project_id=project.id, steps=len(trace))
            return {"text": message, "steps": trace, "status": "completed"}

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
            )
            step = {
                "step": step_number,
                "tool": tool_name,
                "arguments": arguments,
                "status": "ok",
                "result": result,
            }
        except ApprovalRequired as exc:
            step = {
                "step": step_number,
                "tool": tool_name,
                "arguments": arguments,
                "status": "approval_required",
                "permission": exc.permission.value,
            }
            trace.append(step)
            events.emit(
                "tool.approval_required",
                agent_id=agent.id,
                project_id=project.id,
                tool=tool_name,
                permission=exc.permission.value,
            )
            return {
                "text": f"{agent.name} needs approval for {exc.permission.value} before it can continue this task.",
                "steps": trace,
                "status": "waiting_approval",
            }
        except Exception as exc:
            step = {
                "step": step_number,
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
        messages.append({
            "role": "user",
            "content": "TOOL RESULT:\n" + json.dumps(step, ensure_ascii=False, default=str) + "\nContinue with the next tool or finish.",
        })

    events.emit("agent.run.stopped", agent_id=agent.id, project_id=project.id, reason="step_limit")
    return {
        "text": f"Stopped after the V1 safety limit of {MAX_STEPS} tool steps.",
        "steps": trace,
        "status": "step_limit",
    }
