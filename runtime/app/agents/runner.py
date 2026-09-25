from app.providers.registry import get_provider


def run_messages(agent, messages: list[dict[str, str]], endpoint: str | None = None) -> str:
    provider_id = getattr(agent, "_runtime_provider_id", agent.provider_id)
    provider = get_provider(provider_id)
    resolved_endpoint = endpoint or getattr(agent, "_runtime_endpoint", None) or agent.endpoint
    api_key = getattr(agent, "_runtime_api_key", None)
    return provider.chat(
        model=agent.model,
        messages=messages,
        endpoint=resolved_endpoint,
        api_key=api_key,
        temperature=agent.temperature_milli / 1000,
    )


def run_agent(agent, prompt: str, endpoint: str | None = None) -> str:
    return run_messages(
        agent,
        [
            {
                "role": "system",
                "content": f"You are {agent.name}, the {agent.role} agent inside Agent Man.",
            },
            {"role": "user", "content": prompt},
        ],
        endpoint,
    )
