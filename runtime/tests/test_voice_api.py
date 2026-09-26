from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_elevenlabs_config_never_returns_api_key(monkeypatch):
    stored = {}

    monkeypatch.setattr(
        "app.api.voice.secrets.set",
        lambda key, value: stored.__setitem__(key, value),
    )
    monkeypatch.setattr(
        "app.api.voice.secrets.exists",
        lambda key: key in stored,
    )

    response = client.put(
        "/api/voice/elevenlabs/config",
        json={
            "voice_id": "voice-test",
            "model_id": "eleven_flash_v2_5",
            "output_format": "mp3_44100_128",
            "api_key": "super-secret-key",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["provider_id"] == "elevenlabs"
    assert body["voice_id"] == "voice-test"
    assert body["has_secret"] is True
    assert "api_key" not in body
    assert stored["voice:elevenlabs:api_key"] == "super-secret-key"


def test_elevenlabs_voice_discovery_uses_stored_secret(monkeypatch):
    monkeypatch.setattr(
        "app.api.voice.secrets.get",
        lambda key: "stored-key",
    )
    monkeypatch.setattr(
        "app.api.voice.elevenlabs.list_voices",
        lambda **kwargs: [
            {
                "voice_id": "voice-a",
                "name": "Agent Voice",
                "category": "premade",
                "description": "Clear assistant voice",
                "preview_url": None,
                "labels": {"accent": "British"},
            }
        ],
    )

    response = client.get(
        "/api/voice/elevenlabs/voices"
    )

    assert response.status_code == 200
    assert response.json()[0]["voice_id"] == "voice-a"
    assert response.json()[0]["name"] == "Agent Voice"


def test_elevenlabs_speech_streams_audio(monkeypatch):
    monkeypatch.setattr(
        "app.api.voice.secrets.set",
        lambda key, value: None,
    )
    monkeypatch.setattr(
        "app.api.voice.secrets.exists",
        lambda key: True,
    )
    monkeypatch.setattr(
        "app.api.voice.secrets.get",
        lambda key: "stored-key",
    )

    configured = client.put(
        "/api/voice/elevenlabs/config",
        json={
            "voice_id": "voice-stream",
            "model_id": "eleven_flash_v2_5",
            "output_format": "mp3_22050_32",
            "api_key": "stored-key",
        },
    )
    assert configured.status_code == 200

    captured = {}

    class FakeAudio:
        content_type = "audio/mpeg"

        def iter_bytes(self):
            yield b"first"
            yield b"second"

    def fake_open_speech_stream(**kwargs):
        captured.update(kwargs)
        return FakeAudio()

    monkeypatch.setattr(
        "app.api.voice.elevenlabs.open_speech_stream",
        fake_open_speech_stream,
    )

    response = client.post(
        "/api/voice/elevenlabs/speech",
        json={"text": "Agent Man online."},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "audio/mpeg"
    )
    assert response.content == b"firstsecond"
    assert captured["api_key"] == "stored-key"
    assert captured["voice_id"] == "voice-stream"
    assert captured["model_id"] == "eleven_flash_v2_5"
    assert captured["output_format"] == "mp3_22050_32"
    assert captured["text"] == "Agent Man online."


def test_elevenlabs_rejects_unsupported_output_format(monkeypatch):
    monkeypatch.setattr(
        "app.api.voice.secrets.exists",
        lambda key: False,
    )

    response = client.put(
        "/api/voice/elevenlabs/config",
        json={
            "voice_id": "voice-test",
            "model_id": "eleven_flash_v2_5",
            "output_format": "pcm_44100",
        },
    )

    assert response.status_code == 400
