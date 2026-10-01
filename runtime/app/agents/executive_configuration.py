from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.configuration import agent_view, update_configuration
from app.api.schemas import AgentUpdate
from app.persistence.models import AgentRecord, AIConnectionRecord


CONFIGURATION_ACTIONS = {"inspect_agent", "configure_agent", "list_ai_connections"}


def execute_configuration_action(db: Session, project_id: str, action: dict) -> dict:
    if action["type"] == "list_ai_connections":
        return {"connections": [
            {"id": row.id, "name": row.name, "provider_id": row.provider_id,
             "default_model": row.default_model}
            for row in db.scalars(select(AIConnectionRecord)).all()
        ]}
    agent = db.get(AgentRecord, str(action.get("agent_id", "")))
    if agent is None or agent.project_id != project_id:
        raise LookupError("Unknown worker agent in this project")
    if action["type"] == "inspect_agent":
        return {"agent": agent_view(agent).model_dump()}
    changes = action.get("changes")
    if not isinstance(changes, dict) or not changes:
        raise ValueError("changes must be a nonempty object")
    if set(changes) - {"name", "role", "context", "llm"}:
        raise ValueError("Only name, role, context, and llm can be configured")
    changes = dict(changes)
    if "llm" in changes:
        llm = changes["llm"]
        allowed = {"connection_id", "model", "temperature", "context_limit", "cloud_fallback_allowed"}
        if not isinstance(llm, dict) or not llm or set(llm) - allowed:
            raise ValueError("llm must contain connection_id, model, temperature, context_limit, or cloud_fallback_allowed")
        changes["llm"] = {**agent_view(agent).llm.model_dump(), **llm}
    saved = update_configuration(db, agent, AgentUpdate.model_validate(changes))
    return {"agent": saved.model_dump(), "note": "Saved configuration applies to subsequent runs. Running work is not restarted."}
