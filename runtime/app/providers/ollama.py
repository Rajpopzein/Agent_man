import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.providers.base import Provider, ProviderSpec
from app.providers.streaming import stream_json


class OllamaProvider(Provider):
    spec = ProviderSpec(
        id="ollama",
        label="Ollama",
        default_endpoint="http://localhost:11434",
        requires_api_key=False,
        local=True,
    )

    def _request(self, *, method: str, url: str, payload: dict | None = None) -> dict:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(url, data=data, headers={"Content-Type": "application/json"}, method=method)
        try:
            with urlopen(request, timeout=120) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Ollama returned HTTP {exc.code}: {detail[:500]}") from exc
        except URLError as exc:
            raise RuntimeError(f"Could not connect to Ollama: {exc.reason}") from exc

    def chat(self, *, model: str, messages: list[dict[str, str]], endpoint: str | None = None, api_key: str | None = None, temperature: float = 0.2) -> str:
        base = self.resolve_endpoint(endpoint)
        payload = self._request(
            method="POST",
            url=base + "/api/chat",
            payload={
                "model": model,
                "messages": messages,
                "stream": False,
                "options": {"temperature": temperature},
            },
        )
        return payload["message"]["content"]

    def list_models(self, *, endpoint: str | None = None, api_key: str | None = None) -> list[str]:
        base = self.resolve_endpoint(endpoint)
        payload = self._request(method="GET", url=base + "/api/tags")
        return sorted({str(item["name"]) for item in payload.get("models", []) if item.get("name")})

    def stream_chat(self, *, model, messages, endpoint=None, api_key=None, temperature=0.2):
        for item in stream_json(
            self.resolve_endpoint(endpoint) + "/api/chat",
            {"model": model, "messages": messages, "stream": True, "options": {"temperature": temperature}},
            ndjson=True,
        ):
            content = item.get("message", {}).get("content")
            if content:
                yield content
            if item.get("done"):
                return
