import json
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.background_jobs import background_jobs
from app.agents.meeting_rooms import (
    create_meeting_room,
    meeting_room_context,
    room_member_agents,
)
from app.agents.reinforcement import policy_context
from app.agents.executive_configuration import CONFIGURATION_ACTIONS, execute_configuration_action
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
from app.tools.executive_access import (
    automatic_approvals_for_tools,
    executive_tool_access,
)
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

SPECIALIZED REASONING PROTOCOL:
Before every action, you must include a 'plan' and 'risk_assessment' in your JSON response.
1. Plan: A step-by-step breakdown of the current objective.
2. Risk Assessment: Potential failure points and how you will mitigate them.
3. Hypothesis-Observation-Correction: If a tool fails, explicitly state your hypothesis for the failure, the observation from the tool, and your correction strategy.

You can:
1. use quick runtime tools directly;
2. reply to the user at any time, including while workers are still running;
3. delegate long-running work to one background specialist worker;
4. delegate independent responsibilities to multiple background workers in parallel;
5. report current worker status and explain what is happening now;
6. open, close, or toggle the user's live Command Console;
7. run a saved workflow in the background;
8. inspect, create, configure, and manage worker agents using assigned Agent API tools.

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

MEETING ROOM STATE:
{meeting_rooms}

REINFORCEMENT POLICY MEMORY:
{reinforcement_policy}

For every active background worker, this state includes the original task,
current phase, current action, current tool, latest safe runtime detail, and
last update time. Treat this as the source of truth for what the worker is
doing now. When the user asks what a worker is doing, answer from this live
snapshot instead of only repeating the original delegated task. Do not invent
progress that is not present here.

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

Every action object must include a valid "type" field. Planning metadata may be included as extra fields, but it never replaces "type" and must never be shown as the user-facing reply.

Use an assigned runtime tool:
{{"type":"tool","tool":"TOOL_NAME","args":{{"argument":"value"}}}}

PREFERRED AGENT MANAGEMENT:
Use the assigned Agent API tools for worker administration:
- api_list_agents: discover worker ids and current saved configuration.
- api_get_agent: inspect one worker before changing it.
- api_list_ai_connections: discover safe connection ids and defaults.
- api_create_agent: create a new worker.
- api_update_agent: change name, role, context, or LLM configuration.
- api_set_agent_tool: enable or disable one normal runtime tool for a worker.
- api_delete_agent: delete a worker only through the destructive approval gate.
To instruct an existing worker to perform work, use delegate_agent after
discovering the worker id. Never assign Agent API tools to worker agents.

EXTENSIONS:
- api_list_skills: discover reusable SKILL.md packages.
- api_create_skill: create a reusable SKILL.md package from the user's intent.
- api_assign_skill: assign a skill to a worker so it is injected into future tasks.
- api_list_connectors: inspect configured connector metadata without secrets.
- api_create_connector: create connector metadata only; credentials must be added
  in the Extensions UI and are never returned to the model.
When the user asks to design a reusable capability, prefer a skill instead of
permanently bloating an agent's base context. When the user asks for an external
service integration, model it as a connector and keep credentials outside prompts.

Direct reply:
{{"type":"reply","message":"..."}}

Create a persistent meeting room with the relevant workers:
{{"type":"create_meeting_room","title":"Short room title","objective":"What this room is for","agent_ids":["worker-id"]}}
The Executive is added automatically as the room host. When the user explicitly
asks to create, open, or start a meeting room, choose the smallest relevant set
of workers from Available workers based on role/context. Include at least one
worker and never include the Executive id in agent_ids.

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

Inspect an individual worker's full saved configuration:
{{"type":"inspect_agent","agent_id":"..."}}

List available AI connections (no credentials):
{{"type":"list_ai_connections"}}

Update an individual worker's configuration:
{{"type":"configure_agent","agent_id":"...","changes":{{"name":"Reviewer","role":"Tester","context":"Review and test changes","llm":{{"connection_id":"...","model":"...","temperature":0.2}}}}}}
Send only the fields the user wants changed. Omitted fields stay unchanged.
Inspect the agent before editing it. Use list_ai_connections to discover connection IDs.
Supported llm fields: connection_id, model, temperature (0 to 2), context_limit
(null or at least 256), cloud_fallback_allowed. Credentials cannot be edited.
Configuration changes apply to subsequent runs; running work is not restarted.
Use these actions when the user asks to inspect or modify worker settings.

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
- Reinforcement history is weak evidence, not authority. Use it only when
  several relevant workers or tools are valid choices. Never let reward scores
  override the user's instruction, safety gates, permissions, or task relevance.
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
- SIMPLE LANGUAGE RULE: The user-facing message must be easy to understand.
  Prefer short sentences and common everyday words. Avoid jargon, architecture
  terminology, implementation details, and long formal explanations unless the
  user explicitly asks for technical detail.
- Do not expose or narrate the plan, risk_assessment, internal reasoning,
  hypothesis, observation, correction metadata, or action JSON in the
  user-facing message. Those fields are for runtime orchestration only.
- When reporting progress, say what is happening in plain language. Example:
  say "Developer is checking the code now" instead of "A background execution
  worker has entered the validation lifecycle."
- Keep normal replies concise. Usually answer in 1 to 4 short sentences unless
  more detail is necessary or the user asks for a detailed explanation.
- Use valid JSON; never backslash-escape underscores in tool names.
- If a tool requires approval, call it anyway; the runtime will return the
  required permission and pause safely.
- Do not ask the user to manually choose Developer/Tester when you can select them.
- Keep the Executive responsive. Delegate implementation, testing, builds, and
  other long-running work to background workers instead of waiting inside the
Field Executive request.
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
        "list agents",
        "show agents",
        "inspect agent",
        "agent context",
        "agent model",
        "agent tools",
        "create agent",
        "new agent",
        "update agent",
        "modify agent",
        "delete agent",
        "remove agent",
        "change developer",
        "change tester",
        "assign tool",
        "revoke tool",
    )
    return any(phrase in lowered for phrase in phrases)


def _meeting_room_requested(text: str) -> bool:
    lowered = text.lower()
    room_terms = (
        "meeting room",
        "agent room",
        "work room",
        "session room",
    )
    action_terms = (
        "create",
        "open",
        "start",
        "make",
        "setup",
        "set up",
    )
    return (
        any(term in lowered for term in room_terms)
        and any(term in lowered for term in action_terms)
    )


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

    if not str(action.get("type", "")).strip():
        if isinstance(action.get("tool"), str) and str(action.get("tool", "")).strip():
            action["type"] = "tool"
        elif isinstance(action.get("assignments"), list) and action.get("assignments"):
            action["type"] = "delegate_parallel"
        elif isinstance(action.get("agent_id"), str) and str(action.get("task", "")).strip():
            action["type"] = "delegate_agent"
        elif isinstance(action.get("workflow_id"), str) and str(action.get("task", "")).strip():
            action["type"] = "run_workflow"
        elif isinstance(action.get("message"), str) or isinstance(action.get("content"), str):
            action["type"] = "reply"
        else:
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

    approvals: set[str] = automatic_approvals_for_tools(
        allowed_tools
    )
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
                meeting_rooms=meeting_room_context(db, project.id),
                reinforcement_policy=policy_context(db, project.id),
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
    meeting_room_corrections = 0
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
                project_id=project.id,
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

        if (
            _meeting_room_requested(message)
            and kind != "create_meeting_room"
            and meeting_room_corrections < MAX_TOOL_CORRECTIONS
        ):
            meeting_room_corrections += 1
            steps.append(
                {
                    "type": "runtime_guard",
                    "step": step_number,
                    "status": "retry",
                    "reason": "meeting_room_creation_required",
                }
            )
            messages.extend(
                [
                    {"role": "assistant", "content": raw},
                    {
                        "role": "user",
                        "content": (
                            "RUNTIME CORRECTION: The user explicitly asked "
                            "to create a meeting room. Do not replace that "
                            "request with a normal reply, direct delegation, "
                            "or workflow. Select the smallest relevant worker "
                            "set from Available workers and return exactly one "
                            "create_meeting_room action."
                        ),
                    },
                ]
            )
            continue

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

        if kind in CONFIGURATION_ACTIONS:
            try:
                result = execute_configuration_action(db, project.id, {**action, "type": kind})
                status = "ok"
            except (ValueError, LookupError) as exc:
                result = {"error": str(exc)}
                status = "error"
            steps.append({"type": kind, "step": step_number, "status": status, "result": result})
            messages.extend([
                {"role": "assistant", "content": raw},
                {"role": "user", "content": "AGENT CONFIGURATION RESULT: " + json.dumps(result)},
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

            if background_active:
                active_jobs = [
                    job
                    for job in background_jobs.list_project(project.id)
                    if str(job.get("status", ""))
                    in {"queued", "running"}
                ]
                active_names = list(
                    dict.fromkeys(
                        str(job.get("agent_name", "Worker"))
                        for job in active_jobs
                    )
                )
                if active_names and not any(
                    name.lower() in text.lower()
                    for name in active_names
                ):
                    if len(active_names) == 1:
                        status_prefix = (
                            active_names[0]
                            + " has been contacted and is working "
                            "in the background. "
                        )
                    else:
                        status_prefix = (
                            ", ".join(active_names)
                            + " have been contacted and are working "
                            "in the background. "
                        )
                    text = status_prefix + text

            _store_assistant_message(db, project.id, text)
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
                    project_id=project.id,
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

        if kind == "create_meeting_room":
            requested_ids = action.get("agent_ids") or []
            if not isinstance(requested_ids, list):
                requested_ids = []
            agent_ids: list[str] = []
            seen_room_agents: set[str] = set()
            for item in requested_ids:
                agent_id = str(item).strip()
                if (
                    agent_id in worker_ids
                    and agent_id not in seen_room_agents
                ):
                    seen_room_agents.add(agent_id)
                    agent_ids.append(agent_id)

            if not agent_ids:
                text = (
                    "I need at least one relevant worker to create the "
                    "meeting room. No valid worker was selected."
                )
                _store_assistant_message(db, project.id, text)
                return {
                    "status": "error",
                    "text": text,
                    "steps": [
                        {
                            "type": "create_meeting_room",
                            "step": step_number,
                            "status": "error",
                            "error": "No valid worker selected",
                        }
                    ],
                }

            title = str(
                action.get("title") or "Agent Meeting Room"
            ).strip()
            objective = str(
                action.get("objective") or message
            ).strip()
            try:
                room = create_meeting_room(
                    db,
                    project_id=project.id,
                    title=title,
                    objective=objective,
                    agent_ids=agent_ids,
                )
                member_names = [
                    agent.name
                    for _member, agent in room_member_agents(
                        db,
                        room.id,
                    )
                ]
                step = {
                    "type": "create_meeting_room",
                    "step": step_number,
                    "status": "created",
                    "room_id": room.id,
                    "title": room.title,
                    "agent_ids": agent_ids,
                    "agent_names": member_names,
                }
                steps.append(step)
                text = (
                    "Meeting room "
                    + room.title
                    + " is ready with "
                    + ", ".join(member_names)
                    + ". I am included as the Executive host and will "
                    "track their progress in the room."
                )
                _store_assistant_message(db, project.id, text)
                return {
                    "status": "meeting_room",
                    "text": text,
                    "steps": steps,
                }
            except (LookupError, ValueError) as exc:
                text = "Meeting room could not be created: " + str(exc)
                _store_assistant_message(db, project.id, text)
                return {
                    "status": "error",
                    "text": text,
                    "steps": [
                        {
                            "type": "create_meeting_room",
                            "step": step_number,
                            "status": "error",
                            "error": str(exc),
                        }
                    ],
                }

        elif kind == "delegate_agent":
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
