import json
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.executor import execute_agent
from app.agents.multi_agent import run_peer_task
from app.agents.orchestration import execute_workflow_run
from app.agents.runner import run_messages
from app.agents.protocol import special_action
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
from app.tools.executive_access import executive_tool_access
from app.tools.intelligence import (
    plan_tools,
    preflight_tool,
    recovery_guidance,
)
from app.tools.registry import tools

MAX_EXECUTIVE_STEPS = 30
MAX_HISTORY = 20
MAX_TOOL_CORRECTIONS = 3

SYSTEM_PROMPT = """You are Agent Man, the executive agent and primary user interface.
The user talks to you, not directly to worker agents.

You are both an executive coordinator and a direct tool-using agent.

You can:
1. use any runtime tool listed below directly;
2. reply directly for simple conversational questions;
3. delegate a task to one specialist worker;
4. delegate to multiple peers only when the user explicitly asks for parallel or multi-agent work;
5. run a saved workflow.

You are responsible for the overall objective. Use direct tools when you can
efficiently inspect, modify, validate, or operate the project yourself. Delegate
when specialist workers or independent review are useful. After every tool or
delegation result, reassess the overall objective and continue until it is
actually complete.

The runtime enforces permissions. Never bypass approval requirements and never
invent tool results.

RUNTIME TOOL ACCESS IS CONFIRMED.
You currently have {tool_count} effective runtime tools.
These tools are directly executable by the runtime when you emit a valid tool
action. Do not claim you cannot access tools that appear in this list.

Available runtime tools:
{tools}

Effective tool names:
{tool_names}

RUNTIME TOOL PLAN FOR THIS OBJECTIVE:
{tool_plan}

Treat the runtime tool plan as operational guidance, not optional prose. If it
identifies a required tool sequence, start with the first safe prerequisite
instead of guessing arguments that discovery tools can provide.

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
- If the user asks you to inspect, read, list, edit, run, test, build, fetch,
  browse, inspect Git, inspect processes, inspect ports, or access serial/COM
  hardware, use a relevant runtime tool before replying.
- If a tool attempt fails, inspect the failure and follow runtime recovery
  guidance before giving up.
- Never invent a COM port, file path, process id, session id, URL, or other
  runtime identifier when a discovery/inspection tool can obtain it first.
- Tool actions are internal instructions, never a user-facing answer. Final
  replies must explain what was discovered, what actually succeeded or failed,
  and what remains needed. For serial hardware, report the observed port and
  device description, and distinguish discovery from a verified connection.
- Use valid JSON; never backslash-escape underscores in tool names.
- If a tool requires approval, call it anyway; the runtime will return the
  required permission and pause safely.
- Do not ask the user to manually choose Developer/Tester when you can select them.
- Default to one worker at a time. Never use delegate_peers unless the user
  explicitly asks for parallel, multi-agent, peer, swarm, simultaneous, or
  all-agent execution. Sequential handoffs such as Developer then Tester are
  allowed after the current worker returns.
- Only reply with the final user-facing result when the overall objective is complete,
  or when a required runtime permission/capability genuinely prevents progress.
"""


def _looks_like_tool_denial(text: str) -> bool:
    lowered = text.lower()
    phrases = (
        "i don't have access",
        "i do not have access",
        "i can't access",
        "i cannot access",
        "i'm unable to access",
        "i am unable to access",
        "no access to",
        "don't have direct access",
        "do not have direct access",
        "cannot directly access",
        "can't directly access",
        "unable to directly access",
    )
    return any(phrase in lowered for phrase in phrases)


def _request_requires_tool(text: str) -> bool:
    lowered = text.lower()
    phrases = (
        "list files",
        "show files",
        "read file",
        "open file",
        "edit file",
        "write file",
        "search files",
        "run command",
        "execute command",
        "run tests",
        "run test",
        "build project",
        "run build",
        "lint",
        "git status",
        "git diff",
        "git commit",
        "check port",
        "allocate port",
        "list processes",
        "start process",
        "stop process",
        "fetch ",
        "open website",
        "browse ",
        "internet",
        "web access",
        "serial port",
        "com port",
        "esp32",
        "hardware",
    )
    return any(phrase in lowered for phrase in phrases)


def _explicit_parallel_requested(text: str) -> bool:
    lowered = text.lower()
    phrases = (
        "parallel",
        "in parallel",
        "multiple agents",
        "multi agent",
        "multi-agent",
        "peer agents",
        "peer collaboration",
        "swarm",
        "simultaneously",
        "at the same time",
        "all agents",
    )
    return any(phrase in lowered for phrase in phrases)


def _parse(raw: str):
    special = special_action(raw)
    if special is not None:
        return special
    raw = raw.strip()
    try:
        action = json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if start >= 0 and end > start:
            try:
                action = json.loads(raw[start:end + 1])
            except json.JSONDecodeError:
                action = {"type": "invalid_action"}
        else:
            action = {"type": "reply", "message": raw}

    if not isinstance(action, dict):
        action = {"type": "invalid_action"}

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
        (
            f"- {a.id}: {a.name} ({a.role}) model={a.model}; "
            + "context="
            + (
                " ".join(
                    str(getattr(a, "context", "") or "").split()
                )[:1200]
                or "(no custom context)"
            )
        )
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
    allow_hardware: bool,
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
    tool_access = executive_tool_access(
        db,
        project.id,
    )
    allowed_tools = set(tool_access.names)
    tool_plan = plan_tools(message, allowed_tools)

    approvals: set[str] = set()
    if allow_terminal:
        approvals.add(Permission.TERMINAL_EXECUTE.value)
    if allow_delete:
        approvals.add(Permission.PROJECT_DELETE.value)
    if allow_network:
        approvals.add(Permission.NETWORK_ACCESS.value)
    if allow_hardware:
        approvals.add(Permission.SERIAL_ACCESS.value)

    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT.format(
                tools=tool_access.catalog or "(none)",
                tool_count=tool_access.count,
                tool_names=", ".join(tool_access.names) or "(none)",
                tool_plan=tool_plan.prompt_text(),
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
    tool_corrections = 0
    format_corrections = 0

    discovery_tool = preflight_tool(
        tool_plan,
        allowed_tools,
    )
    if discovery_tool:
        try:
            discovery_result = tools.execute(
                name=discovery_tool,
                arguments={},
                workspace_path=project.workspace_path,
                approvals=approvals,
                allowed_names=allowed_tools,
            )
            discovery_step = {
                "type": "tool_preflight",
                "step": 0,
                "tool": discovery_tool,
                "arguments": {},
                "status": "ok",
                "result": discovery_result,
            }
        except Exception as exc:
            discovery_step = {
                "type": "tool_preflight",
                "step": 0,
                "tool": discovery_tool,
                "arguments": {},
                "status": "error",
                "error": str(exc),
            }

        steps.append(discovery_step)
        events.emit(
            "executive.activity",
            project_id=project.id,
            agent_id="main-agent:" + project.id,
            agent_name="Agent Man",
            phase="tool_preflight",
            status=str(discovery_step.get("status", "")),
            label=discovery_tool,
            message=(
                "Discovering runtime data with " + discovery_tool
                if discovery_step.get("status") == "ok"
                else "Discovery failed in " + discovery_tool
            ),
        )
        messages.append(
            {
                "role": "user",
                "content": (
                    "RUNTIME PREFLIGHT RESULT:\n"
                    + json.dumps(
                        discovery_step,
                        ensure_ascii=False,
                        default=str,
                    )
                    + "\nUse this real discovery result when choosing the "
                    "next tool. Never invent a device or runtime identifier."
                ),
            }
        )

    for step_number in range(1, MAX_EXECUTIVE_STEPS + 1):
        raw = run_messages(proxy, messages)
        action = _parse(raw)
        kind = str(action.get("type", "reply")).lower()

        if kind == "invalid_action":
            format_corrections += 1
            steps.append({
                "type": "runtime_guard",
                "step": step_number,
                "status": "retry" if format_corrections <= MAX_TOOL_CORRECTIONS else "error",
                "reason": "invalid_action_json",
            })
            if format_corrections > MAX_TOOL_CORRECTIONS:
                text = (
                    "The executive model returned invalid tool instructions. "
                    "Those instructions were not executed, so I could not "
                    "complete your request. Please retry or select another executive model."
                )
                _store_assistant_message(db, project.id, text)
                return {"status": "error", "text": text, "steps": steps}
            messages.extend([
                {"role": "assistant", "content": raw},
                {"role": "user", "content": (
                    "RUNTIME CORRECTION: Invalid action JSON; this action was not executed. "
                    "Return exactly one valid JSON object. Do not escape underscores. "
                    "Use the discovery results already provided, never guess a COM port. "
                    "Execute tools with type=tool; use type=reply only for a plain-language "
                    "summary of observed results and any remaining blocker."
                )},
            ])
            continue

        if kind == "reply":
            text = str(action.get("message", raw)).strip()
            should_force_tool = (
                bool(allowed_tools)
                and tool_corrections < MAX_TOOL_CORRECTIONS
                and (
                    _looks_like_tool_denial(text)
                    or (
                        not steps
                        and (
                            tool_plan.requires_tool
                            or _request_requires_tool(message)
                        )
                    )
                )
            )

            if should_force_tool:
                tool_corrections += 1
                guard_step = {
                    "type": "runtime_guard",
                    "step": step_number,
                    "status": "retry",
                    "reason": (
                        "false_tool_denial"
                        if _looks_like_tool_denial(text)
                        else "tool_required_for_request"
                    ),
                    "effective_tools": sorted(allowed_tools),
                }
                steps.append(guard_step)
                messages.append(
                    {"role": "assistant", "content": raw}
                )
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "RUNTIME CORRECTION: You DO have direct runtime "
                            "tool access. Effective tools are: "
                            + ", ".join(sorted(allowed_tools))
                            + ". Do not answer that you cannot access the "
                            "system. Use the relevant tool now by returning "
                            "a JSON tool action. If approval is required, "
                            "call the tool and let the runtime request it."
                        ),
                    }
                )
                continue

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

            events.emit(
                "executive.activity",
                project_id=project.id,
                agent_id="main-agent:" + project.id,
                agent_name="Agent Man",
                phase="tool",
                status="started",
                label=tool_name,
                message="Running " + tool_name,
            )

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
                events.emit(
                    "executive.activity",
                    project_id=project.id,
                    agent_id="main-agent:" + project.id,
                    agent_name="Agent Man",
                    phase="tool",
                    status="completed",
                    label=tool_name,
                    message=tool_name + " completed",
                )
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
                events.emit(
                    "executive.activity",
                    project_id=project.id,
                    agent_id="main-agent:" + project.id,
                    agent_name="Agent Man",
                    phase="tool",
                    status="approval_required",
                    label=tool_name,
                    message=(
                        tool_name
                        + " needs "
                        + exc.permission.value
                        + " approval"
                    ),
                )
                text = (
                    "Agent Man needs approval to run "
                    + tool_name
                    + (" on " + str(arguments["device"]) if arguments.get("device") else "")
                    + ". This action has not been executed. Enable "
                    + exc.permission.value
                    + " and retry to continue."
                )
                _store_assistant_message(db, project.id, text)
                return {
                    "status": "waiting_approval",
                    "text": text,
                    "steps": steps,
                }
            except Exception as exc:
                recovery = recovery_guidance(
                    tool_name,
                    str(exc),
                    allowed_tools,
                )
                step = {
                    "type": "tool",
                    "step": step_number,
                    "tool": tool_name,
                    "arguments": arguments,
                    "status": "error",
                    "error": str(exc),
                    "recovery_tools": list(recovery),
                }
                events.emit(
                    "executive.activity",
                    project_id=project.id,
                    agent_id="main-agent:" + project.id,
                    agent_name="Agent Man",
                    phase="tool",
                    status="error",
                    label=tool_name,
                    message=tool_name + " failed: " + str(exc)[:240],
                )

            steps.append(step)
            messages.append({"role": "assistant", "content": raw})
            recovery_text = ""
            if step.get("status") == "error":
                recovery_tools = step.get("recovery_tools") or []
                if recovery_tools:
                    recovery_text = (
                        "\nRUNTIME RECOVERY: Try these assigned discovery/"
                        "prerequisite tools before repeating the failed tool: "
                        + ", ".join(recovery_tools)
                        + "."
                    )
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
                        + recovery_text
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
                events.emit(
                    "executive.activity",
                    project_id=project.id,
                    agent_id="main-agent:" + project.id,
                    agent_name="Agent Man",
                    phase="delegation",
                    status="connecting",
                    label=agent.name,
                    message="Connecting with " + agent.name + "...",
                )
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
                    allow_hardware=allow_hardware,
                )

            step = {
                "type": kind,
                "step": step_number,
                "agent_id": agent_id,
                "result": result,
            }
            steps.append(step)
            events.emit(
                "executive.activity",
                project_id=project.id,
                agent_id="main-agent:" + project.id,
                agent_name="Agent Man",
                phase="delegation",
                status=str(result.get("status", "completed")),
                label=(agent.name if agent_id in worker_ids else "worker"),
                message=(
                    (agent.name if agent_id in worker_ids else "Worker")
                    + " returned to Agent Man"
                ),
            )

        elif kind == "delegate_peers":
            if not _explicit_parallel_requested(message):
                guard_step = {
                    "type": "runtime_guard",
                    "step": step_number,
                    "status": "retry",
                    "reason": "parallel_not_requested",
                }
                steps.append(guard_step)
                events.emit(
                    "executive.activity",
                    project_id=project.id,
                    agent_id="main-agent:" + project.id,
                    agent_name="Agent Man",
                    phase="delegation",
                    status="blocked",
                    label="peer_fanout",
                    message=(
                        "Parallel delegation blocked; selecting one worker"
                    ),
                )
                messages.append(
                    {"role": "assistant", "content": raw}
                )
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "RUNTIME CORRECTION: The user did not request "
                            "parallel or multi-agent execution. Choose at "
                            "most one worker with delegate_agent, use a "
                            "direct tool, or reply if complete."
                        ),
                    }
                )
                continue

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
                    allow_hardware=allow_hardware,
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
                    allow_hardware=allow_hardware,
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
