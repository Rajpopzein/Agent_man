from app.providers.registry import get_provider


def run_messages(agent, messages: list[dict[str, str]], endpoint: str | None = None) -> str:
    provider = get_provider(agent.provider_id)
    return provider.chat(agent.model, messages, endpoint or agent.endpoint)


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
