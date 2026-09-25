import json
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from app.providers.base import Provider, ProviderSpec


class GeminiProvider(Provider):
    spec = ProviderSpec(
        id="gemini",
        label="Google Gemini",
        default_endpoint="https://generativelanguage.googleapis.com/v1beta",
        requires_api_key=True,
        local=False,
    )

    def _request(self, *, method: str, url: str, api_key: str | None, payload: dict | None = None) -> dict:
        self.validate_key(api_key)
        separator = "&" if "?" in url else "?"
        url = url + separator + urlencode({"key": api_key})
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(url, data=data, headers={"Content-Type": "application/json"}, method=method)
        try:
            with urlopen(request, timeout=120) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Gemini returned HTTP {exc.code}: {detail[:500]}") from exc
        except URLError as exc:
            raise RuntimeError(f"Could not connect to Gemini: {exc.reason}") from exc

    def chat(self, *, model: str, messages: list[dict[str, str]], endpoint: str | None = None, api_key: str | None = None, temperature: float = 0.2) -> str:
        base = self.resolve_endpoint(endpoint)
        system_parts = [item["content"] for item in messages if item.get("role") == "system"]
        contents = []
        for item in messages:
            role = item.get("role")
            if role == "system":
                continue
            contents.append({
                "role": "model" if role == "assistant" else "user",
                "parts": [{"text": item.get("content", "")}],
            })

        payload = {
            "contents": contents,
            "generationConfig": {"temperature": temperature},
        }
        if system_parts:
            payload["systemInstruction"] = {"parts": [{"text": "\n".join(system_parts)}]}

        model_name = model.removeprefix("models/")
        result = self._request(
            method="POST",
            url=base + "/models/" + quote(model_name, safe="") + ":generateContent",
            api_key=api_key,
            payload=payload,
        )
        return "".join(str(part.get("text", "")) for part in result["candidates"][0]["content"]["parts"])

    def list_models(self, *, endpoint: str | None = None, api_key: str | None = None) -> list[str]:
        base = self.resolve_endpoint(endpoint)
        payload = self._request(method="GET", url=base + "/models", api_key=api_key)
        models = []
        for item in payload.get("models", []):
            if "generateContent" not in item.get("supportedGenerationMethods", []):
                continue
            name = str(item.get("name", "")).removeprefix("models/")
            if name:
                models.append(name)
        return sorted(set(models))
