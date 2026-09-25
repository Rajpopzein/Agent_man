from app.core.secrets import secrets
from app.persistence.models import AIConnectionRecord
from app.providers.registry import get_provider


def secret_key(connection_id: str) -> str:
    return f"ai-connection:{connection_id}"


def connection_api_key(connection: AIConnectionRecord) -> str | None:
    if not connection.has_secret:
        return None
    return secrets.get(secret_key(connection.id))


def bind_agent_connection(agent, db):
    connection = db.get(AIConnectionRecord, agent.connection_id)
    if connection is None:
        return None
    agent._runtime_provider_id = connection.provider_id
    agent._runtime_endpoint = connection.endpoint
    agent._runtime_api_key = connection_api_key(connection)
    return connection


def list_connection_models(connection: AIConnectionRecord) -> list[str]:
    provider = get_provider(connection.provider_id)
    return provider.list_models(
        endpoint=connection.endpoint,
        api_key=connection_api_key(connection),
    )


def test_connection(connection: AIConnectionRecord) -> dict[str, object]:
    models = list_connection_models(connection)
    return {
        "ok": True,
        "models": models,
        "provider_id": connection.provider_id,
        "endpoint": connection.endpoint,
    }
