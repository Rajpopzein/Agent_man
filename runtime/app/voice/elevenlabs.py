import json
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


ELEVENLABS_BASE = "https://api.elevenlabs.io"
SUPPORTED_OUTPUT_FORMATS = {
    "mp3_22050_32",
    "mp3_44100_128",
}


@dataclass
class ElevenLabsAudioStream:
    response: object
    content_type: str

    def iter_bytes(self, chunk_size: int = 8192):
        try:
            while True:
                chunk = self.response.read(chunk_size)
                if not chunk:
                    break
                yield chunk
        finally:
            self.response.close()


class ElevenLabsClient:
    def _open(
        self,
        *,
        method: str,
        path: str,
        api_key: str,
        payload: dict | None = None,
        query: dict[str, str | int] | None = None,
    ):
        url = ELEVENLABS_BASE + path
        if query:
            url += "?" + urlencode(query)

        body = (
            json.dumps(payload).encode("utf-8")
            if payload is not None
            else None
        )
        request = Request(
            url,
            data=body,
            method=method,
            headers={
                "xi-api-key": api_key,
                "Content-Type": "application/json",
                "Accept": "application/json, audio/mpeg",
            },
        )
        try:
            return urlopen(request, timeout=120)
        except HTTPError as exc:
            detail = exc.read().decode(
                "utf-8",
                errors="replace",
            )
            raise RuntimeError(
                "ElevenLabs returned HTTP "
                + str(exc.code)
                + ": "
                + detail[:600]
            ) from exc
        except URLError as exc:
            raise RuntimeError(
                "Could not connect to ElevenLabs: "
                + str(exc.reason)
            ) from exc

    def list_voices(
        self,
        *,
        api_key: str,
        page_size: int = 100,
    ) -> list[dict]:
        response = self._open(
            method="GET",
            path="/v2/voices",
            api_key=api_key,
            query={
                "page_size": max(1, min(page_size, 100)),
                "sort": "name",
                "sort_direction": "asc",
            },
        )
        try:
            payload = json.loads(
                response.read().decode("utf-8")
            )
        finally:
            response.close()

        result = []
        for item in payload.get("voices", []):
            voice_id = str(item.get("voice_id", "")).strip()
            if not voice_id:
                continue
            labels = item.get("labels") or {}
            result.append(
                {
                    "voice_id": voice_id,
                    "name": str(
                        item.get("name") or voice_id
                    ),
                    "category": str(
                        item.get("category") or ""
                    ),
                    "description": str(
                        item.get("description") or ""
                    ),
                    "preview_url": item.get(
                        "preview_url"
                    ),
                    "labels": {
                        str(key): str(value)
                        for key, value in labels.items()
                    },
                }
            )
        return result

    def open_speech_stream(
        self,
        *,
        api_key: str,
        voice_id: str,
        text: str,
        model_id: str,
        output_format: str,
    ) -> ElevenLabsAudioStream:
        if output_format not in SUPPORTED_OUTPUT_FORMATS:
            raise ValueError(
                "Unsupported ElevenLabs output format: "
                + output_format
            )

        response = self._open(
            method="POST",
            path=(
                "/v1/text-to-speech/"
                + quote(voice_id, safe="")
                + "/stream"
            ),
            api_key=api_key,
            query={
                "output_format": output_format,
            },
            payload={
                "text": text,
                "model_id": model_id,
            },
        )

        content_type = (
            response.headers.get("content-type")
            or "audio/mpeg"
        )
        return ElevenLabsAudioStream(
            response=response,
            content_type=content_type,
        )


elevenlabs = ElevenLabsClient()
