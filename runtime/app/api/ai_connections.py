from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import (
    AIConnectionCreate,
    AIConnectionTestView,
    AIConnectionUpdate,
    AIConnectionView,
    AIProviderView,
)
from app.core.secrets import secrets
from app.persistence.database import get_session
from app.persistence.models import AIConnectionRecord, AgentRecord
from app.providers.connections import (
    list_connection_models,
    secret_key,
    test_connection,
)
from app.providers.registry import get_provider, provider_specs

router = APIRouter(prefix="/api/ai", tags=["ai-connections"])


@router.get("/providers", response_model=list[AIProviderView])
def list_providers():
    return provider_specs()


@router.get("/connections", response_model=list[AIConnectionView])
def list_connections(db: Session = Depends(get_session)):
    rows = db.scalars(
        select(AIConnectionRecord).order_by(AIConnectionRecord.created_at)
    ).all()
    return [connection_view(row) for row in rows]


@router.post("/connections", response_model=AIConnectionView, status_code=201)
def create_connection(
    body: AIConnectionCreate,
    db: Session = Depends(get_session),
):
    try:
        provider = get_provider(body.provider_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    endpoint = body.endpoint or provider.spec.default_endpoint
    if not endpoint:
        raise HTTPException(422, "This provider requires an endpoint")
    if provider.spec.requires_api_key and not body.api_key:
        raise HTTPException(422, "This provider requires an API key")

    row = AIConnectionRecord(
        name=body.name,
        provider_id=body.provider_id,
        endpoint=endpoint.rstrip("/"),
        default_model=body.default_model,
        has_secret=bool(body.api_key),
    )
    db.add(row)
    db.flush()

    try:
        if body.api_key:
            secrets.set(secret_key(row.id), body.api_key)
        db.commit()
    except Exception:
        db.rollback()
        secrets.delete(secret_key(row.id))
        raise

    db.refresh(row)
    return connection_view(row)


@router.patch("/connections/{connection_id}", response_model=AIConnectionView)
def update_connection(
    connection_id: str,
    body: AIConnectionUpdate,
    db: Session = Depends(get_session),
):
    row = require_connection(connection_id, db)
    provider = get_provider(row.provider_id)

    if (
        provider.spec.requires_api_key
        and body.clear_secret
        and not body.api_key
    ):
        raise HTTPException(422, "This provider requires an API key")

    if body.name is not None:
        row.name = body.name
    if body.endpoint is not None:
        endpoint = body.endpoint.rstrip("/")
        if not endpoint:
            raise HTTPException(422, "Endpoint cannot be empty")
        row.endpoint = endpoint
    if body.default_model is not None:
        row.default_model = body.default_model

    if body.clear_secret:
        secrets.delete(secret_key(row.id))
        row.has_secret = False

    if body.api_key:
        secrets.set(secret_key(row.id), body.api_key)
        row.has_secret = True

    if provider.spec.requires_api_key and not row.has_secret:
        raise HTTPException(422, "This provider requires an API key")

    db.commit()
    db.refresh(row)
    return connection_view(row)


@router.delete("/connections/{connection_id}")
def delete_connection(
    connection_id: str,
    db: Session = Depends(get_session),
):
    row = require_connection(connection_id, db)
    in_use = db.scalar(
        select(AgentRecord.id).where(
            AgentRecord.connection_id == connection_id
        ).limit(1)
    )
    if in_use:
        raise HTTPException(
            409,
            "Connection is linked to an agent and cannot be deleted",
        )

    secrets.delete(secret_key(row.id))
    db.delete(row)
    db.commit()
    return {"deleted": True, "id": connection_id}


@router.post(
    "/connections/{connection_id}/test",
    response_model=AIConnectionTestView,
)
def test_saved_connection(
    connection_id: str,
    db: Session = Depends(get_session),
):
    row = require_connection(connection_id, db)
    try:
        return test_connection(row)
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc


@router.get("/connections/{connection_id}/models")
def connection_models(
    connection_id: str,
    db: Session = Depends(get_session),
):
    row = require_connection(connection_id, db)
    try:
        return {"models": list_connection_models(row)}
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc


def require_connection(
    connection_id: str,
    db: Session,
) -> AIConnectionRecord:
    row = db.get(AIConnectionRecord, connection_id)
    if row is None:
        raise HTTPException(404, "AI connection not found")
    return row


def connection_view(row: AIConnectionRecord) -> AIConnectionView:
    return AIConnectionView(
        id=row.id,
        name=row.name,
        provider_id=row.provider_id,
        endpoint=row.endpoint,
        default_model=row.default_model,
        has_secret=row.has_secret,
    )
