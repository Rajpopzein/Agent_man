from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.schemas import (
    ElevenLabsVoiceView,
    VoiceProviderConfigInput,
    VoiceProviderConfigView,
    VoiceSpeechInput,
)
from app.core.secrets import secrets
from app.persistence.database import get_session
from app.persistence.models import VoiceProviderConfigRecord
from app.voice.elevenlabs import (
    SUPPORTED_OUTPUT_FORMATS,
    elevenlabs,
)


router = APIRouter(
    prefix="/api/voice",
    tags=["voice"],
)

PROVIDER_ID = "elevenlabs"
SECRET_KEY = "voice:elevenlabs:api_key"
DEFAULT_MODEL = "eleven_flash_v2_5"
DEFAULT_OUTPUT_FORMAT = "mp3_44100_128"


def _config_view(
    row: VoiceProviderConfigRecord | None,
) -> VoiceProviderConfigView:
    return VoiceProviderConfigView(
        provider_id=PROVIDER_ID,
        voice_id=row.voice_id if row else "",
        model_id=row.model_id if row else DEFAULT_MODEL,
        output_format=(
            row.output_format
            if row
            else DEFAULT_OUTPUT_FORMAT
        ),
        has_secret=(
            bool(row.has_secret)
            if row
            else secrets.exists(SECRET_KEY)
        ),
    )


def _api_key() -> str:
    try:
        key = secrets.get(SECRET_KEY)
    except Exception as exc:
        raise HTTPException(
            500,
            "Unable to read ElevenLabs API key: " + str(exc),
        ) from exc

    if not key:
        raise HTTPException(
            409,
            "Configure the ElevenLabs API key first.",
        )
    return key


@router.get(
    "/elevenlabs/config",
    response_model=VoiceProviderConfigView,
)
def get_elevenlabs_config(
    db: Session = Depends(get_session),
):
    return _config_view(
        db.get(VoiceProviderConfigRecord, PROVIDER_ID)
    )


@router.put(
    "/elevenlabs/config",
    response_model=VoiceProviderConfigView,
)
def set_elevenlabs_config(
    body: VoiceProviderConfigInput,
    db: Session = Depends(get_session),
):
    if body.output_format not in SUPPORTED_OUTPUT_FORMATS:
        raise HTTPException(
            400,
            "Unsupported output format. Use one of: "
            + ", ".join(sorted(SUPPORTED_OUTPUT_FORMATS)),
        )

    row = db.get(VoiceProviderConfigRecord, PROVIDER_ID)
    if row is None:
        row = VoiceProviderConfigRecord(
            provider_id=PROVIDER_ID,
        )
        db.add(row)

    row.voice_id = body.voice_id.strip()
    row.model_id = body.model_id.strip() or DEFAULT_MODEL
    row.output_format = body.output_format

    if body.clear_secret:
        try:
            secrets.delete(SECRET_KEY)
        except Exception as exc:
            raise HTTPException(
                500,
                "Unable to clear ElevenLabs API key: "
                + str(exc),
            ) from exc
        row.has_secret = False
    elif body.api_key is not None and body.api_key.strip():
        try:
            secrets.set(
                SECRET_KEY,
                body.api_key.strip(),
            )
        except Exception as exc:
            raise HTTPException(
                500,
                "Unable to store ElevenLabs API key: "
                + str(exc),
            ) from exc
        row.has_secret = True
    else:
        row.has_secret = secrets.exists(SECRET_KEY)

    db.commit()
    db.refresh(row)
    return _config_view(row)


@router.get(
    "/elevenlabs/voices",
    response_model=list[ElevenLabsVoiceView],
)
def list_elevenlabs_voices():
    try:
        return elevenlabs.list_voices(
            api_key=_api_key(),
            page_size=100,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            502,
            "ElevenLabs voice discovery failed: " + str(exc),
        ) from exc


@router.post("/elevenlabs/test")
def test_elevenlabs():
    try:
        voices = elevenlabs.list_voices(
            api_key=_api_key(),
            page_size=1,
        )
        return {
            "ok": True,
            "voices_visible": len(voices),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            502,
            "ElevenLabs connection test failed: " + str(exc),
        ) from exc


@router.post("/elevenlabs/speech")
def elevenlabs_speech(
    body: VoiceSpeechInput,
    db: Session = Depends(get_session),
):
    row = db.get(VoiceProviderConfigRecord, PROVIDER_ID)
    if row is None or not row.voice_id.strip():
        raise HTTPException(
            409,
            "Select an ElevenLabs voice first.",
        )

    try:
        audio = elevenlabs.open_speech_stream(
            api_key=_api_key(),
            voice_id=row.voice_id,
            text=body.text.strip(),
            model_id=row.model_id or DEFAULT_MODEL,
            output_format=(
                row.output_format
                or DEFAULT_OUTPUT_FORMAT
            ),
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            502,
            "ElevenLabs speech generation failed: " + str(exc),
        ) from exc

    return StreamingResponse(
        audio.iter_bytes(),
        media_type=audio.content_type,
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
