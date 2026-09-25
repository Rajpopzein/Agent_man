from app.providers.gemini import GeminiProvider
from app.providers.ollama import OllamaProvider
from app.providers.openai_compatible import OpenAICompatibleProvider


_PROVIDERS = {
    "lmstudio": OpenAICompatibleProvider(
        provider_id="lmstudio",
        label="LM Studio",
        default_endpoint="http://localhost:1234/v1",
        requires_api_key=False,
        local=True,
    ),
    "ollama": OllamaProvider(),
    "ollama-openai": OpenAICompatibleProvider(
        provider_id="ollama-openai",
        label="Ollama OpenAI Compatibility",
        default_endpoint="http://localhost:11434/v1",
        requires_api_key=False,
        local=True,
    ),
    "openai": OpenAICompatibleProvider(
        provider_id="openai",
        label="OpenAI",
        default_endpoint="https://api.openai.com/v1",
        requires_api_key=True,
        local=False,
    ),
    "gemini": GeminiProvider(),
    "openai-compatible": OpenAICompatibleProvider(
        provider_id="openai-compatible",
        label="Custom OpenAI-compatible",
        default_endpoint=None,
        requires_api_key=False,
        local=False,
    ),
}


def get_provider(provider_id: str):
    try:
        return _PROVIDERS[provider_id]
    except KeyError as exc:
        raise ValueError(f"Unsupported provider: {provider_id}") from exc


def provider_specs() -> list[dict[str, object]]:
    return [
        {
            "id": provider.spec.id,
            "label": provider.spec.label,
            "default_endpoint": provider.spec.default_endpoint,
            "requires_api_key": provider.spec.requires_api_key,
            "local": provider.spec.local,
        }
        for key, provider in _PROVIDERS.items()
        if key != "ollama-openai"
    ]
