from __future__ import annotations

from dataclasses import dataclass
import re

from app.tools.registry import TOOL_DEFINITIONS


@dataclass(frozen=True)
class ToolPlan:
    intent: str
    reason: str
    recommended_tools: tuple[str, ...]
    sequence: tuple[str, ...]
    missing_tools: tuple[str, ...]
    requires_tool: bool

    def prompt_text(self) -> str:
        if not self.requires_tool:
            return (
                "No runtime tool is required by the objective yet. "
                "Use tools if later evidence requires them."
            )

        recommended = (
            ", ".join(self.recommended_tools)
            if self.recommended_tools
            else "(none currently assigned)"
        )
        sequence = (
            " -> ".join(self.sequence)
            if self.sequence
            else "(choose the safest relevant assigned tool)"
        )
        missing = (
            ", ".join(self.missing_tools)
            if self.missing_tools
            else "(none)"
        )
        return (
            f"Intent: {self.intent}\n"
            f"Why tools are needed: {self.reason}\n"
            f"Recommended assigned tools: {recommended}\n"
            f"Preferred sequence: {sequence}\n"
            f"Missing recommended tools: {missing}"
        )


@dataclass(frozen=True)
class IntentRule:
    intent: str
    terms: tuple[str, ...]
    sequence: tuple[str, ...]
    reason: str


RULES: tuple[IntentRule, ...] = (
    IntentRule(
        intent="serial_hardware",
        terms=(
            "esp32",
            "esp 32",
            "serial",
            "com port",
            "uart",
            "usb serial",
            "microcontroller",
            "devkit",
            "board output",
            "serial monitor",
        ),
        sequence=(
            "list_serial_ports",
            "serial_open",
            "serial_read",
            "serial_write",
            "serial_close",
        ),
        reason=(
            "The objective refers to local serial hardware. Discover the "
            "enumerated port before opening or communicating with it."
        ),
    ),
    IntentRule(
        intent="filesystem",
        terms=(
            "project files",
            "list files",
            "show files",
            "read file",
            "open file",
            "edit file",
            "write file",
            "search files",
            "find file",
            "folder",
            "directory",
            "codebase",
        ),
        sequence=(
            "list_files",
            "search_files",
            "read_file",
            "edit_file",
            "write_file",
        ),
        reason=(
            "The objective requires observing or changing project files."
        ),
    ),
    IntentRule(
        intent="development_validation",
        terms=(
            "run test",
            "run tests",
            "test this",
            "validate",
            "build project",
            "run build",
            "compile",
            "lint",
        ),
        sequence=("run_tests", "run_build", "lint"),
        reason=(
            "The objective requires executable validation rather than a "
            "model-only answer."
        ),
    ),
    IntentRule(
        intent="git",
        terms=(
            "git status",
            "git diff",
            "commit",
            "changes in git",
            "working tree",
        ),
        sequence=("git_status", "git_diff", "git_commit"),
        reason="The objective requires Git repository state or actions.",
    ),
    IntentRule(
        intent="network",
        terms=(
            "internet",
            "web",
            "fetch url",
            "fetch website",
            "open website",
            "http",
            "documentation online",
            "latest docs",
        ),
        sequence=("http_get",),
        reason="The objective requires public network information.",
    ),
    IntentRule(
        intent="runtime_process",
        terms=(
            "process",
            "start server",
            "stop server",
            "background process",
            "service output",
            "process output",
        ),
        sequence=(
            "list_processes",
            "start_process",
            "read_process_output",
            "stop_process",
        ),
        reason="The objective requires managed local process control.",
    ),
    IntentRule(
        intent="runtime_port",
        terms=(
            "port available",
            "check port",
            "free port",
            "allocate port",
            "port conflict",
        ),
        sequence=("check_port", "allocate_port"),
        reason="The objective requires local TCP port inspection/allocation.",
    ),
)


def plan_tools(
    objective: str,
    allowed_names: set[str],
) -> ToolPlan:
    lowered = objective.lower()

    matches: list[IntentRule] = [
        rule
        for rule in RULES
        if any(term in lowered for term in rule.terms)
    ]

    if not matches:
        semantic = _semantic_tool_match(
            objective,
            allowed_names,
        )
        if semantic:
            return ToolPlan(
                intent="tool_semantic_match",
                reason=(
                    "The objective contains operational language that "
                    "matches assigned runtime tool capabilities."
                ),
                recommended_tools=semantic,
                sequence=semantic,
                missing_tools=(),
                requires_tool=True,
            )

        return ToolPlan(
            intent="general",
            reason="No strong runtime-tool intent detected.",
            recommended_tools=(),
            sequence=(),
            missing_tools=(),
            requires_tool=False,
        )

    # Prefer the most specific rule by number of matching terms.
    rule = max(
        matches,
        key=lambda candidate: sum(
            1 for term in candidate.terms if term in lowered
        ),
    )

    sequence = _specialize_sequence(
        rule.intent,
        lowered,
        rule.sequence,
    )
    recommended = tuple(
        name for name in sequence if name in allowed_names
    )
    missing = tuple(
        name for name in sequence if name not in allowed_names
    )

    return ToolPlan(
        intent=rule.intent,
        reason=rule.reason,
        recommended_tools=recommended,
        sequence=sequence,
        missing_tools=missing,
        requires_tool=True,
    )


def recovery_guidance(
    tool_name: str,
    error_text: str,
    allowed_names: set[str],
) -> tuple[str, ...]:
    lowered = error_text.lower()
    candidates: list[str] = []

    if tool_name == "serial_open":
        if (
            "enumerated" in lowered
            or "device" in lowered
            or "port" in lowered
        ):
            candidates.append("list_serial_ports")
    elif tool_name in {"serial_read", "serial_write"}:
        if "session" in lowered or "closed" in lowered:
            candidates.extend(
                ["serial_list_sessions", "list_serial_ports", "serial_open"]
            )
    elif tool_name == "read_file":
        if "not found" in lowered or "no such" in lowered:
            candidates.extend(["search_files", "list_files"])
    elif tool_name == "edit_file":
        candidates.extend(["read_file", "search_files"])
    elif tool_name == "run_tests":
        candidates.extend(["list_files", "read_file"])
    elif tool_name == "start_process":
        if "port" in lowered:
            candidates.extend(["check_port", "allocate_port"])

    return tuple(
        name
        for name in candidates
        if name in allowed_names and name != tool_name
    )


def _specialize_sequence(
    intent: str,
    lowered: str,
    sequence: tuple[str, ...],
) -> tuple[str, ...]:
    if intent != "serial_hardware":
        return sequence

    wants_write = any(
        term in lowered
        for term in (
            "write",
            "send",
            "command",
            "control",
            "turn on",
            "turn off",
        )
    )
    wants_read = any(
        term in lowered
        for term in (
            "read",
            "output",
            "monitor",
            "logs",
            "see what",
            "check",
            "access",
        )
    )

    result = ["list_serial_ports", "serial_open"]
    if wants_read or not wants_write:
        result.append("serial_read")
    if wants_write:
        result.append("serial_write")
    result.append("serial_close")
    return tuple(result)



SAFE_PREFLIGHT_BY_INTENT: dict[str, str] = {
    "serial_hardware": "list_serial_ports",
}


def preflight_tool(
    plan: ToolPlan,
    allowed_names: set[str],
) -> str | None:
    tool_name = SAFE_PREFLIGHT_BY_INTENT.get(plan.intent)
    if tool_name and tool_name in allowed_names:
        return tool_name
    return None



_ACTION_TERMS = {
    "access",
    "check",
    "connect",
    "discover",
    "edit",
    "execute",
    "fetch",
    "find",
    "inspect",
    "list",
    "monitor",
    "open",
    "read",
    "run",
    "search",
    "show",
    "start",
    "status",
    "stop",
    "test",
    "validate",
    "write",
}

_STOPWORDS = {
    "a",
    "an",
    "and",
    "for",
    "from",
    "i",
    "in",
    "is",
    "it",
    "me",
    "my",
    "of",
    "on",
    "the",
    "this",
    "to",
    "with",
    "you",
}


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9_]+", value.lower())
        if len(token) > 1 and token not in _STOPWORDS
    }


def _semantic_tool_match(
    objective: str,
    allowed_names: set[str],
) -> tuple[str, ...]:
    objective_tokens = _tokens(objective)
    if not objective_tokens.intersection(_ACTION_TERMS):
        return ()

    ranked: list[tuple[int, str]] = []

    for tool in TOOL_DEFINITIONS:
        if tool.name not in allowed_names:
            continue

        name_tokens = _tokens(tool.name.replace("_", " "))
        category_tokens = _tokens(tool.category)
        description_tokens = _tokens(tool.description)
        argument_tokens = _tokens(
            " ".join(
                list(tool.arguments.keys())
                + list(tool.arguments.values())
            )
        )

        score = (
            4 * len(objective_tokens & name_tokens)
            + 2 * len(objective_tokens & category_tokens)
            + len(objective_tokens & description_tokens)
            + len(objective_tokens & argument_tokens)
        )
        if score >= 2:
            ranked.append((score, tool.name))

    ranked.sort(key=lambda item: (-item[0], item[1]))
    return tuple(name for _, name in ranked[:4])
