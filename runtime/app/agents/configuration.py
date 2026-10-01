"""Shared, validated agent configuration for Settings and the Executive."""
from sqlalchemy.orm import Session

from app.api.schemas import AgentUpdate, AgentView, LLMConfigInput
from app.events.bus import events
from app.persistence.models import AgentRecord, AIConnectionRecord


def agent_view(row: AgentRecord) -> AgentView:
    return AgentView(
        id=row.id, project_id=row.project_id, name=row.name, role=row.role,
        context=row.context or "", state=row.state,
        llm=LLMConfigInput(
            provider_id=row.provider_id, connection_id=row.connection_id,
            model=row.model, endpoint=row.endpoint, context_limit=row.context_limit,
            temperature=row.temperature_milli / 1000,
            cloud_fallback_allowed=row.cloud_fallback_allowed,
        ),
    )


def update_configuration(db: Session, agent: AgentRecord, body: AgentUpdate) -> AgentView:
    # Validate everything before mutating the record.
    for field in ("name", "role"):
        value = getattr(body, field)
        if value is not None and not value.strip():
            raise ValueError(f"{field.capitalize()} is required")
    connection = None
    if body.llm is not None:
        connection = db.get(AIConnectionRecord, body.llm.connection_id)
        if connection is None:
            raise LookupError("AI connection not found")
        if not body.llm.model.strip():
            raise ValueError("Model is required")
    for field in ("name", "role", "context"):
        value = getattr(body, field)
        if value is not None:
            setattr(agent, field, value.strip())
    if body.llm is not None:
        llm = body.llm
        agent.connection_id = connection.id
        agent.provider_id = connection.provider_id
        agent.endpoint = connection.endpoint
        agent.model = llm.model.strip()
        agent.context_limit = llm.context_limit
        agent.temperature_milli = round(llm.temperature * 1000)
        agent.cloud_fallback_allowed = llm.cloud_fallback_allowed
    db.commit()
    db.refresh(agent)
    events.emit("agent.configuration.updated", project_id=agent.project_id,
                agent_id=agent.id, agent_name=agent.name)
    return agent_view(agent)
