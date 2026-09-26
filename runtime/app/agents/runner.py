import json
from time import perf_counter
from uuid import uuid4

from app.agents.protocol import response_preview
from app.events.bus import events

from app.persistence.database import SessionLocal
from app.persistence.models import LLMLogRecord
from app.providers.registry import get_provider

MAX_LOG_CHARS = 80_000


def _clip(value: str) -> str:
    if len(value) <= MAX_LOG_CHARS:
        return value
    return value[:MAX_LOG_CHARS] + "\n...[truncated]"


def _write_log(
    *,
    agent,
    provider_id: str,
    endpoint: str | None,
    messages: list[dict[str, str]],
    status: str,
    duration_ms: int,
    response_text: str = "",
    error_text: str = "",
) -> None:
    try:
        request_json = _clip(
            json.dumps(
                messages,
                ensure_ascii=False,
                default=str,
            )
        )
        with SessionLocal() as db:
            db.add(
                LLMLogRecord(
                    project_id=getattr(agent, "project_id", None),
                    actor_id=getattr(agent, "id", None),
                    actor_name=str(getattr(agent, "name", "Agent")),
                    actor_role=str(getattr(agent, "role", "Unknown")),
                    provider_id=provider_id,
                    model=str(getattr(agent, "model", "")),
                    endpoint=endpoint,
                    status=status,
                    duration_ms=duration_ms,
                    request_json=request_json,
                    response_text=_clip(response_text),
                    error_text=_clip(error_text),
                )
            )
            db.commit()
    except Exception:
        # Logging must never break an LLM call.
        pass


def run_messages(
    agent,
    messages: list[dict[str, str]],
    endpoint: str | None = None,
) -> str:
    provider_id = getattr(agent, "_runtime_provider_id", agent.provider_id)
    provider = get_provider(provider_id)
    resolved_endpoint = (
        endpoint
        or getattr(agent, "_runtime_endpoint", None)
        or agent.endpoint
    )
    api_key = getattr(agent, "_runtime_api_key", None)
    started = perf_counter()
    response_id = str(uuid4())
    event_context = {
        "project_id": getattr(agent, "project_id", None),
        "agent_id": getattr(agent, "id", None),
        "agent_name": str(getattr(agent, "name", "Agent")),
        "response_id": response_id,
    }
    structured = any(
        item.get("role") == "system" and "Return exactly one JSON object" in item.get("content", "")
        for item in messages
    )
    events.emit("agent.response.started", **event_context, text="")
    result = ""

    try:
        kwargs = dict(
            model=agent.model,
            messages=messages,
            endpoint=resolved_endpoint,
            api_key=api_key,
            temperature=agent.temperature_milli / 1000,
        )
        chunks = provider.stream_chat(**kwargs) if hasattr(provider, "stream_chat") else [provider.chat(**kwargs)]
        last_emitted = started
        last_text = ""
        for chunk in chunks:
            result += chunk
            now = perf_counter()
            text = response_preview(result, structured=structured)
            should_emit = bool(
                text
                and text != last_text
                and (
                    not last_text
                    or now - last_emitted >= 0.03
                    or len(text) - len(last_text) >= 24
                )
            )
            if should_emit:
                events.emit(
                    "agent.response.delta",
                    **event_context,
                    text=text,
                )
                last_text = text
                last_emitted = now

        if not result.strip():
            raise RuntimeError("The model returned an empty response stream.")

        final_preview = response_preview(
            result,
            structured=structured,
        )
        events.emit(
            "agent.response.completed",
            **event_context,
            text=final_preview,
        )
    except Exception as exc:
        events.emit("agent.response.error", **event_context,
                    text="Response interrupted. Check the request error and retry.")
        _write_log(
            agent=agent,
            provider_id=provider_id,
            endpoint=resolved_endpoint,
            messages=messages,
            status="error",
            duration_ms=round((perf_counter() - started) * 1000),
            error_text=str(exc),
        )
        raise

    _write_log(
        agent=agent,
        provider_id=provider_id,
        endpoint=resolved_endpoint,
        messages=messages,
        status="success",
        duration_ms=round((perf_counter() - started) * 1000),
        response_text=result,
    )
    return result


def run_agent(agent, prompt: str, endpoint: str | None = None) -> str:
    return run_messages(
        agent,
        [
            {
                "role": "system",
                "content": (
                    f"You are {agent.name}, the {agent.role} "
                    "agent inside Agent Man.\n\n"
                    "AGENT CONTEXT:\n"
                    + (
                        str(getattr(agent, "context", "")).strip()
                        or "(no custom context provided)"
                    )
                    + "\n\nThe context defines your responsibilities "
                    "and scope. It does not grant runtime tools or "
                    "permissions."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        endpoint,
    )
