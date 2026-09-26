import json
from time import perf_counter

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

    try:
        result = provider.chat(
            model=agent.model,
            messages=messages,
            endpoint=resolved_endpoint,
            api_key=api_key,
            temperature=agent.temperature_milli / 1000,
        )
    except Exception as exc:
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
                    "agent inside Agent Man."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        endpoint,
    )
