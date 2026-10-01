from __future__ import annotations

from dataclasses import dataclass
import json
import math
from typing import Any, Iterable


DEFAULT_CONTEXT_LIMIT = 8_192
DEFAULT_OUTPUT_RESERVE = 4_096
DEFAULT_SAFETY_MARGIN = 2_048
RUNTIME_PAYLOAD_MAX_CHARS = 12_000
AGGRESSIVE_RUNTIME_PAYLOAD_MAX_CHARS = 4_000

_CONTEXT_OVERFLOW_MARKERS = (
    "prompt is longer than the context length",
    "maximum context length",
    "context length exceeded",
    "context_length_exceeded",
    "context window",
    "too many tokens",
    "token limit exceeded",
)


def estimate_text_tokens(value: str) -> int:
    """Conservative dependency-free token estimate for mixed prose/code."""
    if not value:
        return 0
    byte_count = len(value.encode("utf-8"))
    return max(1, math.ceil(byte_count / 3))


def estimate_messages_tokens(messages: Iterable[dict[str, Any]]) -> int:
    total = 2
    for message in messages:
        total += 6
        total += estimate_text_tokens(str(message.get("role", "")))
        total += estimate_text_tokens(str(message.get("content", "")))
    return total


def is_context_overflow_error(error: BaseException | str) -> bool:
    lowered = str(error).lower()
    return any(marker in lowered for marker in _CONTEXT_OVERFLOW_MARKERS)


def _clip_middle(value: str, max_chars: int, label: str) -> str:
    if max_chars <= 0:
        return ""
    if len(value) <= max_chars:
        return value

    marker = (
        "\n...["
        + label
        + "; omitted "
        + str(len(value) - max_chars)
        + " characters]...\n"
    )
    available = max(0, max_chars - len(marker))
    if available <= 16:
        return value[:max_chars]

    head = int(available * 0.58)
    tail = available - head
    return value[:head] + marker + value[-tail:]


def compact_runtime_payload(
    value: Any,
    *,
    max_chars: int = RUNTIME_PAYLOAD_MAX_CHARS,
) -> str:
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(
            value,
            ensure_ascii=False,
            default=str,
        )
    return _clip_middle(
        text,
        max_chars,
        "runtime result compacted",
    )


@dataclass(frozen=True)
class ContextBudgetReport:
    context_limit: int
    input_budget: int
    original_tokens: int
    final_tokens: int
    compacted: bool
    aggressive: bool
    dropped_messages: int
    clipped_messages: int
    summary_messages: int
    critical_clipped: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "context_limit": self.context_limit,
            "input_budget": self.input_budget,
            "original_tokens": self.original_tokens,
            "final_tokens": self.final_tokens,
            "compacted": self.compacted,
            "aggressive": self.aggressive,
            "dropped_messages": self.dropped_messages,
            "clipped_messages": self.clipped_messages,
            "summary_messages": self.summary_messages,
            "critical_clipped": self.critical_clipped,
        }


class ContextBudgetManager:
    def __init__(
        self,
        *,
        context_limit: int | None,
        output_reserve: int | None = None,
        safety_margin: int | None = None,
    ):
        limit = int(context_limit or DEFAULT_CONTEXT_LIMIT)
        self.context_limit = max(256, limit)

        if output_reserve is None:
            output_reserve = min(
                DEFAULT_OUTPUT_RESERVE,
                max(64, self.context_limit // 8),
            )
        if safety_margin is None:
            safety_margin = min(
                DEFAULT_SAFETY_MARGIN,
                max(32, self.context_limit // 16),
            )

        reserve = max(0, int(output_reserve))
        margin = max(0, int(safety_margin))
        max_reserved = max(64, self.context_limit // 2)
        if reserve + margin > max_reserved:
            scale = max_reserved / max(1, reserve + margin)
            reserve = int(reserve * scale)
            margin = int(margin * scale)

        self.output_reserve = reserve
        self.safety_margin = margin
        self.input_budget = max(
            128,
            self.context_limit - reserve - margin,
        )

    def fit(
        self,
        messages: list[dict[str, Any]],
        *,
        aggressive: bool = False,
        force: bool = False,
    ) -> tuple[list[dict[str, str]], ContextBudgetReport]:
        normalized = self._normalize(messages)
        original_tokens = estimate_messages_tokens(normalized)
        target_budget = self.input_budget
        if aggressive:
            # A server can expose less context than the configured model value.
            # On overflow retry, reduce to roughly one quarter of the normal
            # input budget so the retry is materially smaller.
            target_budget = max(256, int(self.input_budget * 0.25))

        if original_tokens <= target_budget and not force:
            clean = self._strip_metadata(normalized)
            return clean, ContextBudgetReport(
                context_limit=self.context_limit,
                input_budget=target_budget,
                original_tokens=original_tokens,
                final_tokens=estimate_messages_tokens(clean),
                compacted=False,
                aggressive=aggressive,
                dropped_messages=0,
                clipped_messages=0,
                summary_messages=0,
                critical_clipped=False,
            )

        work = [dict(item) for item in normalized]
        clipped_messages = 0
        dropped_messages = 0
        summary_messages = 0
        critical_clipped = False

        runtime_limit = (
            AGGRESSIVE_RUNTIME_PAYLOAD_MAX_CHARS
            if aggressive
            else RUNTIME_PAYLOAD_MAX_CHARS
        )
        for item in work:
            if item.get("_context_priority") == "critical":
                continue
            content = str(item.get("content", ""))
            if self._looks_like_runtime_payload(content) and len(content) > runtime_limit:
                item["content"] = _clip_middle(
                    content,
                    runtime_limit,
                    "runtime payload compacted",
                )
                clipped_messages += 1

        if estimate_messages_tokens(work) > target_budget:
            mandatory = self._mandatory_indexes(work)
            recent_keep = 4 if aggressive else 10
            recent_indexes = set(range(max(0, len(work) - recent_keep), len(work)))
            keep = mandatory | recent_indexes
            dropped: list[dict[str, Any]] = []

            for index, item in enumerate(work):
                if estimate_messages_tokens(work) <= target_budget:
                    break
                if index in keep:
                    continue
                if item.get("_context_priority") in {"critical", "high"}:
                    continue
                dropped.append(item)
                work[index] = {
                    "role": "_drop",
                    "content": "",
                    "_context_priority": "low",
                }
                dropped_messages += 1

            work = [item for item in work if item.get("role") != "_drop"]

            if dropped:
                summary = self._conversation_summary(
                    dropped,
                    aggressive=aggressive,
                )
                if summary:
                    summary_item = {
                        "role": "user",
                        "content": summary,
                        "_context_priority": "normal",
                    }
                    insert_at = 1 if work and work[0].get("role") == "system" else 0
                    candidate = work[:insert_at] + [summary_item] + work[insert_at:]
                    if estimate_messages_tokens(candidate) <= target_budget:
                        work = candidate
                        summary_messages = 1

        if estimate_messages_tokens(work) > target_budget:
            for item in work:
                if estimate_messages_tokens(work) <= target_budget:
                    break
                if item.get("_context_priority") == "critical":
                    continue
                content = str(item.get("content", ""))
                max_chars = 1_500 if aggressive else 4_000
                if len(content) > max_chars:
                    item["content"] = _clip_middle(
                        content,
                        max_chars,
                        "message compacted",
                    )
                    clipped_messages += 1

        if estimate_messages_tokens(work) > target_budget:
            for item in work:
                if item.get("role") != "system":
                    continue
                current = estimate_messages_tokens(work)
                if current <= target_budget:
                    break
                overflow = current - target_budget
                current_content = str(item.get("content", ""))
                current_tokens = estimate_text_tokens(current_content)
                target_tokens = max(
                    192,
                    current_tokens - overflow - 64,
                )
                compacted = self._compact_system(
                    current_content,
                    target_tokens=target_tokens,
                )
                if compacted != current_content:
                    item["content"] = compacted
                    clipped_messages += 1

        if estimate_messages_tokens(work) > target_budget:
            # Remove any remaining non-critical messages from oldest to newest.
            reduced: list[dict[str, Any]] = []
            for item in work:
                if (
                    item.get("_context_priority") == "critical"
                    or item.get("role") == "system"
                ):
                    reduced.append(item)
                    continue
                if estimate_messages_tokens(reduced + [item]) <= target_budget:
                    reduced.append(item)
                else:
                    dropped_messages += 1
            work = reduced

        if estimate_messages_tokens(work) > target_budget:
            # Last resort: keep the critical task, but clip oversized critical
            # payloads rather than sending a request that the provider will
            # reject with HTTP 400.
            for item in reversed(work):
                if estimate_messages_tokens(work) <= target_budget:
                    break
                if item.get("role") == "system":
                    continue
                content = str(item.get("content", ""))
                current = estimate_messages_tokens(work)
                overflow = current - target_budget
                target_tokens = max(
                    96,
                    estimate_text_tokens(content) - overflow - 32,
                )
                max_chars = max(192, target_tokens * 3)
                clipped = _clip_middle(
                    content,
                    max_chars,
                    "critical message compacted",
                )
                if clipped != content:
                    item["content"] = clipped
                    clipped_messages += 1
                    critical_clipped = True

        if estimate_messages_tokens(work) > target_budget and work:
            # If the system prompt itself is larger than the model can accept,
            # reduce it to a minimal critical extract.
            for item in work:
                if item.get("role") == "system":
                    item["content"] = self._compact_system(
                        str(item.get("content", "")),
                        target_tokens=max(128, target_budget // 2),
                    )
                    clipped_messages += 1
                    break

        clean = self._strip_metadata(work)

        # Guarantee the provider never receives a locally known oversized
        # package. This only activates for pathological tiny context limits.
        while estimate_messages_tokens(clean) > target_budget and len(clean) > 1:
            removable = next(
                (
                    index
                    for index, item in enumerate(clean[:-1])
                    if item.get("role") != "system"
                ),
                None,
            )
            if removable is None:
                break
            clean.pop(removable)
            dropped_messages += 1

        final_tokens = estimate_messages_tokens(clean)
        return clean, ContextBudgetReport(
            context_limit=self.context_limit,
            input_budget=target_budget,
            original_tokens=original_tokens,
            final_tokens=final_tokens,
            compacted=(
                original_tokens != final_tokens
                or dropped_messages > 0
                or clipped_messages > 0
            ),
            aggressive=aggressive,
            dropped_messages=dropped_messages,
            clipped_messages=clipped_messages,
            summary_messages=summary_messages,
            critical_clipped=critical_clipped,
        )

    @staticmethod
    def _normalize(
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for item in messages:
            normalized.append(
                {
                    "role": str(item.get("role", "user")),
                    "content": str(item.get("content", "")),
                    "_context_priority": str(
                        item.get("_context_priority", "normal")
                    ),
                }
            )
        return normalized

    @staticmethod
    def _strip_metadata(
        messages: list[dict[str, Any]],
    ) -> list[dict[str, str]]:
        return [
            {
                "role": str(item.get("role", "user")),
                "content": str(item.get("content", "")),
            }
            for item in messages
        ]

    @staticmethod
    def _mandatory_indexes(
        messages: list[dict[str, Any]],
    ) -> set[int]:
        mandatory = {
            index
            for index, item in enumerate(messages)
            if item.get("_context_priority") == "critical"
        }
        if messages and messages[0].get("role") == "system":
            mandatory.add(0)

        # Preserve the latest user message as a fallback even if the caller did
        # not explicitly tag the current task.
        for index in range(len(messages) - 1, -1, -1):
            if messages[index].get("role") == "user":
                mandatory.add(index)
                break
        return mandatory

    @staticmethod
    def _looks_like_runtime_payload(content: str) -> bool:
        stripped = content.lstrip()
        return stripped.startswith(
            (
                "TOOL RESULT:",
                "RUNTIME PREFLIGHT RESULT:",
                "AGENT CONFIGURATION RESULT:",
                "BACKGROUND DISPATCH COMPLETE",
                "CAPABILITY RESOLVED:",
            )
        )

    @staticmethod
    def _conversation_summary(
        messages: list[dict[str, Any]],
        *,
        aggressive: bool,
    ) -> str:
        if not messages:
            return ""

        max_items = 4 if aggressive else 8
        excerpt_chars = 120 if aggressive else 240
        lines = [
            "OLDER CONVERSATION COMPACTED BY RUNTIME:",
            "Only short excerpts are retained. The current task and recent "
            "runtime state take priority.",
        ]
        for item in messages[-max_items:]:
            role = str(item.get("role", "user")).upper()
            content = " ".join(str(item.get("content", "")).split())
            if len(content) > excerpt_chars:
                content = content[:excerpt_chars] + "..."
            lines.append(role + ": " + content)
        return "\n".join(lines)

    @staticmethod
    def _compact_system(
        content: str,
        *,
        target_tokens: int,
    ) -> str:
        if estimate_text_tokens(content) <= target_tokens:
            return content

        max_chars = max(384, target_tokens * 3)
        lines = content.splitlines()
        markers = (
            "return exactly",
            "never ",
            "do not ",
            "approval",
            "permission",
            "runtime",
            "current user",
            "user-facing",
            "rules:",
            "tool access",
            "available tools",
        )
        critical_lines: list[str] = []
        seen: set[str] = set()
        for line in lines:
            stripped = line.strip()
            lowered = stripped.lower()
            if (
                stripped
                and any(marker in lowered for marker in markers)
                and stripped not in seen
            ):
                critical_lines.append(stripped)
                seen.add(stripped)
            if len(critical_lines) >= 48:
                break

        head = content[: min(len(content), max_chars // 3)]
        tail = content[-min(len(content), max_chars // 3) :]
        candidate = (
            head
            + "\n\n...[system context compacted by runtime]...\n\n"
            + "\n".join(critical_lines)
            + "\n\n...[end critical extract]...\n\n"
            + tail
        )
        return _clip_middle(
            candidate,
            max_chars,
            "system prompt compacted",
        )
