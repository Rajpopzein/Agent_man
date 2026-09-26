from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderSpec:
    id: str
    label: str
    default_endpoint: str | None
    requires_api_key: bool
    local: bool


class Provider(ABC):
    spec: ProviderSpec

    def stream_chat(self, **kwargs):
        yield self.chat(**kwargs)

    @abstractmethod
    def chat(self, *, model: str, messages: list[dict[str, str]], endpoint: str | None = None, api_key: str | None = None, temperature: float = 0.2) -> str:
        raise NotImplementedError

    @abstractmethod
    def list_models(self, *, endpoint: str | None = None, api_key: str | None = None) -> list[str]:
        raise NotImplementedError

    def resolve_endpoint(self, endpoint: str | None) -> str:
        resolved = endpoint or self.spec.default_endpoint
        if not resolved:
            raise ValueError(f"{self.spec.label} requires an endpoint")
        return resolved.rstrip("/")

    def validate_key(self, api_key: str | None) -> None:
        if self.spec.requires_api_key and not api_key:
            raise ValueError(f"{self.spec.label} requires an API key")
