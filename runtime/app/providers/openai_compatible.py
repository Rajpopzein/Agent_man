import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.providers.base import Provider, ProviderSpec
from app.providers.streaming import stream_json


class OpenAICompatibleProvider(Provider):
    def __init__(self, *, provider_id: str, label: str, default_endpoint: str | None, requires_api_key: bool, local: bool):
        self.spec = ProviderSpec(provider_id, label, default_endpoint, requires_api_key, local)

    def _request(self, *, method: str, url: str, api_key: str | None, payload: dict | None = None) -> dict:
        self.validate_key(api_key)
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(url, data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=120) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"{self.spec.label} returned HTTP {exc.code}: {detail[:500]}") from exc
        except URLError as exc:
            raise RuntimeError(f"Could not connect to {self.spec.label}: {exc.reason}") from exc

    def chat(self, *, model: str, messages: list[dict[str, str]], endpoint: str | None = None, api_key: str | None = None, temperature: float = 0.2) -> str:
        base = self.resolve_endpoint(endpoint)
        payload = self._request(
            method="POST",
            url=base + "/chat/completions",
            api_key=api_key,
            payload={"model": model, "messages": messages, "temperature": temperature},
        )
        return payload["choices"][0]["message"]["content"]

    def list_models(self, *, endpoint: str | None = None, api_key: str | None = None) -> list[str]:
        base = self.resolve_endpoint(endpoint)
        payload = self._request(method="GET", url=base + "/models", api_key=api_key)
        return sorted({str(item["id"]) for item in payload.get("data", []) if item.get("id")})

    def stream_chat(self, *, model, messages, endpoint=None, api_key=None, temperature=0.2):
        self.validate_key(api_key)
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        for item in stream_json(
            self.resolve_endpoint(endpoint) + "/chat/completions",
            {"model": model, "messages": messages, "temperature": temperature, "stream": True},
            headers,
        ):
            for choice in item.get("choices", []):
                if choice.get("index", 0) != 0:
                    continue
                content = choice.get("delta", {}).get("content")
                if content:
                    yield content
