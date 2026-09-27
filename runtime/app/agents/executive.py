import json
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.background_jobs import background_jobs
from app.agents.runner import run_messages
from app.agents.protocol import special_action
from app.agents.self_improvement import (
    UPGRADE_MUTATING_TOOLS,
    UPGRADE_VALIDATION_TOOLS,
    find_upgrade,
    is_self_upgrade_intent,
    normalize_text_list,
    parse_upgrade_command,
    upgrade_context,
)
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
    SelfUpgradeProposalRecord,
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
1. use quick runtime tools directly;
2. reply to the user at any time, including while workers are still running;
3. delegate long-running work to one background specialist worker;
4. delegate independent responsibilities to multiple background workers in parallel;
5. report current worker status and explain what is happening now;
6. open, close, or toggle the user's live Command Console;
7. run a saved workflow in the background.

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

BACKGROUND EXECUTION STATE:
{background_jobs}

SELF-IMPROVEMENT STATE:
{upgrades}

Self-correction is runtime controlled. When a tool fails, inspect only the
observable failure and recovery guidance, choose a safer revised action, and
do not repeat an identical failing action indefinitely.

If the user explicitly asks Agent Man to improve or upgrade itself, first
produce an upgrade proposal instead of silently editing runtime code:
{{"type":"propose_upgrade","title":"Short title","reason":"Observed limitation","changes":["Scoped change"],"validation":["Test or build"]}}

Only an upgrade already approved by the user may be applied. After making the
approved changes and successfully validating them, mark that proposal applied:
{{"type":"mark_upgrade_applied","proposal_id":"..."}}

Return exactly one JSON object and no markdown.

Use an assigned runtime tool:
{{"type":"tool","tool":"TOOL_NAME","args":{{"argument":"value"}}}}

Direct reply:
{{"type":"reply","message":"..."}}

Delegate one worker in the background:
{{"type":"delegate_agent","agent_id":"...","task":"..."}}

Delegate independent work in parallel:
{{"type":"delegate_parallel","assignments":[{{"agent_id":"...","task":"..."}},{{"agent_id":"...","task":"..."}}]}}

Backward-compatible same-task parallel delegation:
{{"type":"delegate_peers","agent_ids":["...","..."],"task":"..."}}

Control the live Command Console:
{{"type":"command_console","action":"open"}}
{{"type":"command_console","action":"close"}}
{{"type":"command_console","action":"toggle"}}

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
  guidance before giving up. Prefer a different safe approach when the same
  action has already failed.
- Never approve your own self-upgrade proposal. Approval belongs to the user.
- Never mark an upgrade applied until an actual scoped change and validation
  have both succeeded.
- Never invent a COM port, file path, process id, session id, URL, or other
  runtime identifier when a discovery/inspection tool can obtain it first.
- Tool actions are internal instructions, never a user-facing answer. Final
  replies must explain what was discovered, what actually succeeded or failed,
  and what remains needed. For serial hardware, report the observed port and
  device description, and distinguish discovery from a verified connection.
- User-facing replies may be spoken aloud. Write them as natural conversational
  speech. Do not narrate internal action names such as propose_upgrade,
  delegate_agent, JSON schemas, braces, backticks, Markdown syntax, or raw file
  paths unless the user explicitly asks for those technical details. Summarize
  internal operations in plain language instead.
- Use valid JSON; never backslash-escape underscores in tool names.
- If a tool requires approval, call it anyway; the runtime will return the
  required permission and pause safely.
- Do not ask the user to manually choose Developer/Tester when you can select them.
- Keep the Executive responsive. Delegate implementation, testing, builds, and
  other long-running work to background workers instead of waiting inside the
  Executive request.
- Parallelize only work that is meaningfully independent. Do not intentionally
  assign two workers to edit the same files at the same time.
- After launching background work, do not wait for completion. Tell the user
  what started, what each worker is doing, and that they can ask for status or
  give another instruction immediately.
- When the user asks for status, explain the current process using BACKGROUND
  EXECUTION STATE and worker states. Distinguish queued, running, completed,
  waiting approval, and failed work.
- You may open the Command Console when the user asks to see logs/terminal
  activity or when live execution evidence would materially help. Never expose
  hidden reasoning; the console contains runtime events and tool/process output.
- A background objective may still be in progress when you reply. Do not claim
  it is complete until the relevant background jobs actually completed.
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
            f"- {a.id}: {a.name} ({a.role}) state={a.state} model={a.model}; "
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

    upgrade_command = parse_upgrade_command(message)
    active_upgrade = None

    if upgrade_command and upgrade_command[0] in {"approve", "reject"}:
        decision, token = upgrade_command
        proposal = find_upgrade(db, project.id, token)
        if proposal is None:
            text = (
                "I could not find a unique upgrade proposal matching "
                + token
                + "."
            )
            _store_assistant_message(db, project.id, text)
            return {"status": "error", "text": text, "steps": []}

        if decision == "approve":
            if proposal.status not in {"proposed", "approved"}:
                text = (
                    "Upgrade "
                    + proposal.id
                    + " cannot be approved from status "
                    + proposal.status
                    + "."
                )
                _store_assistant_message(db, project.id, text)
                return {"status": "error", "text": text, "steps": []}
            proposal.status = "approved"
            verb = "approved"
        else:
            if proposal.status == "applied":
                text = "An applied upgrade cannot be rejected."
                _store_assistant_message(db, project.id, text)
                return {"status": "error", "text": text, "steps": []}
            proposal.status = "rejected"
            verb = "rejected"

        db.commit()
        events.emit(
            "self_upgrade.status_changed",
            project_id=project.id,
            proposal_id=proposal.id,
            status=proposal.status,
        )
        text = (
            "Upgrade "
            + proposal.id
            + " is "
            + verb
            + "."
            + (
                " Say 'apply upgrade "
                + proposal.id
                + "' when you want Agent Man to execute it."
                if proposal.status == "approved"
                else ""
            )
        )
        _store_assistant_message(db, project.id, text)
        return {
            "status": "completed",
            "text": text,
            "steps": [
                {
                    "type": "self_upgrade",
                    "proposal_id": proposal.id,
                    "status": proposal.status,
                }
            ],
        }

    if upgrade_command and upgrade_command[0] == "apply":
        proposal = find_upgrade(
            db,
            project.id,
            upgrade_command[1],
        )
        if proposal is None:
            text = (
                "I could not find a unique upgrade proposal matching "
                + upgrade_command[1]
                + "."
            )
            _store_assistant_message(db, project.id, text)
            return {"status": "error", "text": text, "steps": []}
        if proposal.status != "approved":
            text = (
                "Upgrade "
                + proposal.id
                + " is "
                + proposal.status
                + ", not approved. Approve it before applying it."
            )
            _store_assistant_message(db, project.id, text)
            return {
                "status": "waiting_upgrade_approval",
                "text": text,
                "steps": [
                    {
                        "type": "self_upgrade",
                        "proposal_id": proposal.id,
                        "status": proposal.status,
                    }
                ],
            }
        active_upgrade = proposal

    upgrade_intent = (
        is_self_upgrade_intent(message)
        or active_upgrade is not None
    )

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
                background_jobs=background_jobs.context_text(project.id),
                upgrades=upgrade_context(db, project.id),
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
    correction_count = 0
    active_correction: dict | None = None
    last_failure_signature = ""
    repeated_failure_count = 0
    upgrade_changed = False
    upgrade_validated = False

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

            if active_upgrade is not None and active_upgrade.status == "approved":
                steps.append(
                    {
                        "type": "runtime_guard",
                        "step": step_number,
                        "status": "retry",
                        "reason": "approved_upgrade_not_finalized",
                        "proposal_id": active_upgrade.id,
                        "change_succeeded": upgrade_changed,
                        "validation_succeeded": upgrade_validated,
                    }
                )
                messages.append({"role": "assistant", "content": raw})
                if not upgrade_changed:
                    instruction = (
                        "The approved upgrade has not changed anything yet. "
                        "Apply only the scoped approved changes using assigned tools."
                    )
                elif not upgrade_validated:
                    instruction = (
                        "The approved upgrade has changed files but is not validated. "
                        "Run an assigned validation tool such as run_tests, run_build, "
                        "or lint before completion."
                    )
                else:
                    instruction = (
                        "The approved upgrade is changed and validated. "
                        "Return mark_upgrade_applied for proposal "
                        + active_upgrade.id
                        + " before the final reply."
                    )
                messages.append(
                    {
                        "role": "user",
                        "content": "RUNTIME UPGRADE GATE: " + instruction,
                    }
                )
                continue

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
            background_active = any(
                step.get("type")
                in {
                    "delegate_agent",
                    "delegate_parallel",
                    "delegate_peers",
                    "run_workflow",
                }
                and str(
                    (step.get("result") or {}).get("status", "")
                )
                in {"queued", "running", "partial"}
                for step in steps
            )
            return {
                "status": (
                    "background"
                    if background_active
                    else "completed"
                ),
                "text": text,
                "steps": steps,
            }

        if kind == "tool":
            tool_name = str(action.get("tool", ""))
            arguments = action.get("args") or {}
            if not isinstance(arguments, dict):
                arguments = {}

            if (
                upgrade_intent
                and active_upgrade is None
                and tool_name in UPGRADE_MUTATING_TOOLS
            ):
                guard_step = {
                    "type": "runtime_guard",
                    "step": step_number,
                    "status": "blocked",
                    "reason": "self_upgrade_requires_approval",
                    "tool": tool_name,
                }
                steps.append(guard_step)
                events.emit(
                    "self_upgrade.blocked",
                    project_id=project.id,
                    tool=tool_name,
                    reason="approval_required",
                )
                messages.append({"role": "assistant", "content": raw})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "RUNTIME UPGRADE GATE: Self-upgrade mutations are "
                            "blocked until the user approves a proposal. Inspect "
                            "with read-only tools if needed, then return "
                            "propose_upgrade with scoped changes and validation."
                        ),
                    }
                )
                continue

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
                if tool_name in {
                    "run_command",
                    "run_tests",
                    "run_build",
                    "lint",
                    "read_process_output",
                }:
                    events.emit(
                        "runtime.console",
                        project_id=project.id,
                        agent_id="main-agent:" + project.id,
                        agent_name="Agent Man",
                        source=tool_name,
                        status="ok",
                        message=json.dumps(
                            result,
                            ensure_ascii=False,
                            default=str,
                        )[-8000:],
                    )

                if active_upgrade is not None:
                    if tool_name in UPGRADE_MUTATING_TOOLS:
                        upgrade_changed = True
                    if tool_name in UPGRADE_VALIDATION_TOOLS:
                        upgrade_validated = True

                if active_correction is not None:
                    recovery_step = {
                        "type": "self_correction",
                        "step": step_number,
                        "status": "recovered",
                        "failed_tool": active_correction["failed_tool"],
                        "recovery_tool": tool_name,
                    }
                    steps.append(recovery_step)
                    events.emit(
                        "agent.self_correction",
                        project_id=project.id,
                        agent_id="main-agent:" + project.id,
                        agent_name="Agent Man",
                        status="recovered",
                        failed_tool=active_correction["failed_tool"],
                        recovery_tool=tool_name,
                    )
                    active_correction = None
                    last_failure_signature = ""
                    repeated_failure_count = 0
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

                failure_signature = (
                    tool_name
                    + ":"
                    + json.dumps(
                        arguments,
                        sort_keys=True,
                        ensure_ascii=False,
                        default=str,
                    )
                )
                if failure_signature == last_failure_signature:
                    repeated_failure_count += 1
                else:
                    last_failure_signature = failure_signature
                    repeated_failure_count = 1

                correction_count += 1
                active_correction = {
                    "failed_tool": tool_name,
                    "error": str(exc),
                    "recovery_tools": list(recovery),
                }
                correction_step = {
                    "type": "self_correction",
                    "step": step_number,
                    "status": "replanning",
                    "failed_tool": tool_name,
                    "error": str(exc),
                    "recovery_tools": list(recovery),
                    "correction_number": correction_count,
                    "repeated_identical_failure": repeated_failure_count,
                }
                steps.append(step)
                steps.append(correction_step)
                events.emit(
                    "agent.self_correction",
                    project_id=project.id,
                    agent_id="main-agent:" + project.id,
                    agent_name="Agent Man",
                    status="replanning",
                    failed_tool=tool_name,
                    recovery_tools=list(recovery),
                    correction_number=correction_count,
                )

            if step.get("status") != "error":
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
                        + (
                            "\nSELF-CORRECTION CHECKPOINT: Do not repeat the "
                            "identical failing action unchanged again. Choose "
                            "a recovery prerequisite or a different safe plan."
                            if (
                                step.get("status") == "error"
                                and repeated_failure_count >= 2
                            )
                            else ""
                        )
                        + "\nContinue the overall objective. If the tool "
                        "failed, inspect the observable error and revise the "
                        "approach when possible."
                    ),
                }
            )
            continue

        if kind == "propose_upgrade":
            changes = normalize_text_list(action.get("changes"))
            validation = normalize_text_list(action.get("validation"))
            title = " ".join(str(action.get("title", "")).split())[:200]
            reason = " ".join(str(action.get("reason", "")).split())[:4000]

            if not title or not reason or not changes or not validation:
                messages.append({"role": "assistant", "content": raw})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "RUNTIME CORRECTION: An upgrade proposal requires "
                            "a title, reason, at least one scoped change, and at "
                            "least one validation step."
                        ),
                    }
                )
                continue

            if not upgrade_intent and correction_count < 2:
                messages.append({"role": "assistant", "content": raw})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "RUNTIME UPGRADE GATE: Finish the user's current "
                            "objective. A self-upgrade proposal is allowed only "
                            "when the user asked for it or repeated runtime "
                            "failures show a concrete limitation."
                        ),
                    }
                )
                continue

            proposal = SelfUpgradeProposalRecord(
                project_id=project.id,
                title=title,
                reason=reason,
                changes_json=json.dumps(changes, ensure_ascii=False),
                validation_json=json.dumps(validation, ensure_ascii=False),
                status="proposed",
            )
            db.add(proposal)
            db.commit()
            db.refresh(proposal)
            proposal_step = {
                "type": "self_upgrade",
                "step": step_number,
                "proposal_id": proposal.id,
                "status": "proposed",
                "title": proposal.title,
                "reason": proposal.reason,
                "changes": changes,
                "validation": validation,
            }
            steps.append(proposal_step)
            events.emit(
                "self_upgrade.proposed",
                project_id=project.id,
                proposal_id=proposal.id,
                title=proposal.title,
                status="proposed",
            )
            text = (
                "I created self-upgrade proposal "
                + proposal.id
                + ": "
                + proposal.title
                + ". Review it, then say 'approve upgrade "
                + proposal.id
                + "' or 'reject upgrade "
                + proposal.id
                + "'. I will not modify myself until it is approved."
            )
            _store_assistant_message(db, project.id, text)
            return {
                "status": "waiting_upgrade_approval",
                "text": text,
                "steps": steps,
            }

        if kind == "mark_upgrade_applied":
            proposal_id = str(action.get("proposal_id", "")).strip()
            proposal = find_upgrade(db, project.id, proposal_id)
            if (
                active_upgrade is None
                or proposal is None
                or proposal.id != active_upgrade.id
                or proposal.status != "approved"
            ):
                messages.append({"role": "assistant", "content": raw})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "RUNTIME UPGRADE GATE: Only the active user-approved "
                            "upgrade may be marked applied."
                        ),
                    }
                )
                continue
            if not upgrade_changed or not upgrade_validated:
                messages.append({"role": "assistant", "content": raw})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "RUNTIME UPGRADE GATE: Do not mark this upgrade "
                            "applied until a scoped change and a validation tool "
                            "have both succeeded."
                        ),
                    }
                )
                continue

            proposal.status = "applied"
            db.commit()
            active_upgrade = proposal
            applied_step = {
                "type": "self_upgrade",
                "step": step_number,
                "proposal_id": proposal.id,
                "status": "applied",
            }
            steps.append(applied_step)
            events.emit(
                "self_upgrade.status_changed",
                project_id=project.id,
                proposal_id=proposal.id,
                status="applied",
            )
            messages.append({"role": "assistant", "content": raw})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "UPGRADE STATE: Proposal "
                        + proposal.id
                        + " is now APPLIED after successful change and validation. "
                        "Return a concise final summary."
                    ),
                }
            )
            continue

        if kind == "command_console":
            console_action = str(
                action.get("action", "toggle")
            ).strip().lower()
            if console_action not in {"open", "close", "toggle"}:
                console_action = "toggle"
            step = {
                "type": "command_console",
                "step": step_number,
                "action": console_action,
                "status": "ok",
            }
            steps.append(step)
            events.emit(
                "ui.command_console",
                project_id=project.id,
                agent_id="main-agent:" + project.id,
                agent_name="Agent Man",
                action=console_action,
                message="Command Console " + console_action,
            )
            messages.append({"role": "assistant", "content": raw})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "UI RESULT: Command Console action '"
                        + console_action
                        + "' was sent to the interface. Continue with a "
                        "normal user-facing response or the next task action."
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
            task_text = str(action.get("task", message)).strip()

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
                    task=task_text[:500],
                    state="assigned",
                )
                try:
                    result = background_jobs.start_agent(
                        project_id=project.id,
                        agent_id=agent.id,
                        agent_name=agent.name,
                        agent_role=agent.role,
                        task=task_text,
                        allow_terminal=allow_terminal,
                        allow_delete=allow_delete,
                        allow_network=allow_network,
                        allow_hardware=allow_hardware,
                    )
                except ValueError as exc:
                    result = {
                        "status": "error",
                        "error": str(exc),
                    }

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
                status=str(result.get("status", "queued")),
                label=(agent.name if agent_id in worker_ids else "worker"),
                message=(
                    (agent.name if agent_id in worker_ids else "Worker")
                    + (
                        " is running in background"
                        if result.get("status") in {"queued", "running"}
                        else " could not be started"
                    )
                ),
            )

        elif kind in {"delegate_parallel", "delegate_peers"}:
            assignments: list[tuple[str, str]] = []
            if kind == "delegate_parallel":
                raw_assignments = action.get("assignments") or []
                if isinstance(raw_assignments, list):
                    for item in raw_assignments:
                        if not isinstance(item, dict):
                            continue
                        agent_id = str(item.get("agent_id", ""))
                        task_text = str(item.get("task", "")).strip()
                        if agent_id in worker_ids and task_text:
                            assignments.append((agent_id, task_text))
            else:
                task_text = str(action.get("task", message)).strip()
                for item in action.get("agent_ids", []):
                    agent_id = str(item)
                    if agent_id in worker_ids:
                        assignments.append((agent_id, task_text))

            unique: list[tuple[str, str]] = []
            seen_agents: set[str] = set()
            for agent_id, task_text in assignments:
                if agent_id in seen_agents:
                    continue
                seen_agents.add(agent_id)
                unique.append((agent_id, task_text))

            jobs: list[dict] = []
            errors: list[dict] = []
            if len(unique) < 2:
                errors.append({
                    "error": "At least two valid independent worker assignments are required."
                })
            else:
                for agent_id, task_text in unique:
                    agent = db.get(AgentRecord, agent_id)
                    agent.state = "assigned"
                    db.commit()
                    events.emit(
                        "agent.delegated",
                        agent_id=agent.id,
                        agent_name=agent.name,
                        agent_role=agent.role,
                        project_id=project.id,
                        task=task_text[:500],
                        state="assigned",
                    )
                    try:
                        jobs.append(
                            background_jobs.start_agent(
                                project_id=project.id,
                                agent_id=agent.id,
                                agent_name=agent.name,
                                agent_role=agent.role,
                                task=task_text,
                                allow_terminal=allow_terminal,
                                allow_delete=allow_delete,
                                allow_network=allow_network,
                                allow_hardware=allow_hardware,
                            )
                        )
                    except ValueError as exc:
                        errors.append({
                            "agent_id": agent_id,
                            "error": str(exc),
                        })

            result = {
                "status": (
                    "queued"
                    if jobs and not errors
                    else "partial"
                    if jobs
                    else "error"
                ),
                "jobs": jobs,
                "errors": errors,
            }
            step = {
                "type": kind,
                "step": step_number,
                "agent_ids": [item[0] for item in unique],
                "result": result,
            }
            steps.append(step)
            events.emit(
                "executive.activity",
                project_id=project.id,
                agent_id="main-agent:" + project.id,
                agent_name="Agent Man",
                phase="delegation",
                status=result["status"],
                label="parallel_workers",
                message=(
                    str(len(jobs))
                    + " workers launched in parallel; Executive remains available."
                ),
            )

        elif kind == "run_workflow":
            workflow_id = str(action.get("workflow_id", ""))
            task_text = str(action.get("task", message)).strip()

            if workflow_id not in workflow_ids:
                result = {
                    "status": "error",
                    "error": "Unknown workflow",
                }
            else:
                workflow = db.get(WorkflowRecord, workflow_id)
                result = background_jobs.start_workflow(
                    project_id=project.id,
                    workflow_id=workflow.id,
                    workflow_name=workflow.name,
                    task=task_text,
                    allow_terminal=allow_terminal,
                    allow_delete=allow_delete,
                    allow_network=allow_network,
                    allow_hardware=allow_hardware,
                )

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
                    + (
                        "\nBACKGROUND DISPATCH COMPLETE. Do not wait for the "
                        "worker result. Reply to the user now with which work "
                        "started, the current process, and that the Executive "
                        "remains available for status questions or new commands."
                        if step.get("type") in {
                            "delegate_agent",
                            "delegate_parallel",
                            "delegate_peers",
                            "run_workflow",
                        }
                        and str(
                            (step.get("result") or {}).get("status", "")
                        ) in {"queued", "running", "partial"}
                        else
                        "\nReassess the overall objective. Use direct tools, "
                        "delegate again, or reply when appropriate."
                    )
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
