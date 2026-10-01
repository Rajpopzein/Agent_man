from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.agents.configuration import agent_view
from app.agents.executive_configuration import execute_configuration_action
from app.core.permissions import Permission, require
from app.events.bus import events
from app.persistence.models import (
    AIConnectionRecord,
    AgentRecord,
    AgentToolRecord,
    MultiAgentMessageRecord,
    MultiAgentParticipantRecord,
    ProjectRecord,
    ToolRecord,
    WorkflowNodeRecord,
    WorkflowRunStepRecord,
)
from app.tools.policy import EXECUTIVE_ONLY_TOOL_NAMES


def _project(db: Session, project_id: str) -> ProjectRecord:
    project = db.get(ProjectRecord, project_id)
    if project is None:
        raise LookupError("Project not found")
    return project


def _agent(db: Session, project_id: str, agent_id: str) -> AgentRecord:
    agent = db.get(AgentRecord, agent_id)
    if agent is None or agent.project_id != project_id:
        raise LookupError("Unknown worker agent in this project")
    return agent


def _assigned_tools(db: Session, agent_id: str) -> list[str]:
    rows = db.execute(
        select(AgentToolRecord.tool_name)
        .join(
            ToolRecord,
            ToolRecord.name == AgentToolRecord.tool_name,
        )
        .where(
            AgentToolRecord.agent_id == agent_id,
            AgentToolRecord.enabled.is_(True),
            ToolRecord.enabled.is_(True),
        )
        .order_by(AgentToolRecord.tool_name)
    ).all()
    return [row[0] for row in rows]


def _agent_payload(db: Session, agent: AgentRecord) -> dict[str, Any]:
    return {
        **agent_view(agent).model_dump(),
        "tools": _assigned_tools(db, agent.id),
    }


def list_agents(db: Session, project_id: str) -> dict[str, Any]:
    _project(db, project_id)
    rows = db.scalars(
        select(AgentRecord)
        .where(AgentRecord.project_id == project_id)
        .order_by(AgentRecord.created_at)
    ).all()
    return {
        "agents": [
            _agent_payload(db, agent)
            for agent in rows
        ]
    }


def get_agent(
    db: Session,
    project_id: str,
    agent_id: str,
) -> dict[str, Any]:
    return {
        "agent": _agent_payload(
            db,
            _agent(db, project_id, agent_id),
        )
    }


def list_ai_connections(db: Session) -> dict[str, Any]:
    rows = db.scalars(
        select(AIConnectionRecord).order_by(
            AIConnectionRecord.created_at
        )
    ).all()
    return {
        "connections": [
            {
                "id": row.id,
                "name": row.name,
                "provider_id": row.provider_id,
                "endpoint": row.endpoint,
                "default_model": row.default_model,
                "has_secret": row.has_secret,
            }
            for row in rows
        ]
    }


def create_agent(
    db: Session,
    project_id: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    _project(db, project_id)
    require(Permission.PROJECT_WRITE)

    name = str(arguments.get("name", "")).strip()
    role = str(arguments.get("role", "")).strip()
    context = str(arguments.get("context", "")).strip()
    connection_id = str(
        arguments.get("connection_id", "")
    ).strip()
    if not name:
        raise ValueError("Agent name is required")
    if not role:
        raise ValueError("Agent role is required")
    if not connection_id:
        raise ValueError("AI connection id is required")

    connection = db.get(AIConnectionRecord, connection_id)
    if connection is None:
        raise LookupError("AI connection not found")

    model = str(
        arguments.get("model")
        or connection.default_model
        or ""
    ).strip()
    if not model:
        raise ValueError("Model is required")

    temperature = float(arguments.get("temperature", 0.2))
    if temperature < 0 or temperature > 2:
        raise ValueError("Temperature must be between 0 and 2")

    context_limit_raw = arguments.get("context_limit")
    context_limit = (
        int(context_limit_raw)
        if context_limit_raw is not None
        else None
    )
    if context_limit is not None and context_limit < 256:
        raise ValueError(
            "Context limit must be at least 256"
        )

    agent = AgentRecord(
        project_id=project_id,
        name=name,
        role=role,
        context=context,
        provider_id=connection.provider_id,
        connection_id=connection.id,
        model=model,
        endpoint=connection.endpoint,
        context_limit=context_limit,
        temperature_milli=round(temperature * 1000),
        cloud_fallback_allowed=bool(
            arguments.get("cloud_fallback_allowed", False)
        ),
    )
    db.add(agent)
    db.flush()
    from app.tools.service import ensure_agent_defaults
    ensure_agent_defaults(db, agent.id)
    db.commit()
    db.refresh(agent)

    events.emit(
        "agent.created",
        project_id=project_id,
        agent_id=agent.id,
        agent_name=agent.name,
        agent_role=agent.role,
        source="executive_api",
    )
    return {
        "agent": _agent_payload(db, agent),
        "note": "The new worker is available for future delegation.",
    }


def update_agent(
    db: Session,
    project_id: str,
    agent_id: str,
    changes: dict[str, Any],
) -> dict[str, Any]:
    require(Permission.PROJECT_WRITE)
    _agent(db, project_id, agent_id)
    result = execute_configuration_action(
        db,
        project_id,
        {
            "type": "configure_agent",
            "agent_id": agent_id,
            "changes": changes,
        },
    )
    return {
        **result,
        "source": "executive_api",
    }


def set_agent_tool(
    db: Session,
    project_id: str,
    agent_id: str,
    tool_name: str,
    enabled: bool,
) -> dict[str, Any]:
    require(Permission.PROJECT_WRITE)
    _agent(db, project_id, agent_id)

    if tool_name in EXECUTIVE_ONLY_TOOL_NAMES:
        raise ValueError(
            "Executive-only tools cannot be assigned to workers"
        )

    tool = db.get(ToolRecord, tool_name)
    if tool is None:
        raise LookupError("Tool not found")
    if enabled and not tool.enabled:
        raise ValueError("Runtime-disabled tool cannot be assigned")

    assignment = db.get(
        AgentToolRecord,
        {
            "agent_id": agent_id,
            "tool_name": tool_name,
        },
    )
    if assignment is None:
        assignment = AgentToolRecord(
            agent_id=agent_id,
            tool_name=tool_name,
            enabled=enabled,
        )
        db.add(assignment)
    else:
        assignment.enabled = enabled

    db.commit()
    events.emit(
        "agent.tool_assignment.updated",
        project_id=project_id,
        agent_id=agent_id,
        tool_name=tool_name,
        enabled=enabled,
        source="executive_api",
    )
    return {
        "agent_id": agent_id,
        "tool_name": tool_name,
        "enabled": enabled,
        "tools": _assigned_tools(db, agent_id),
    }


def delete_agent(
    db: Session,
    project_id: str,
    agent_id: str,
    approvals: set[str] | None,
) -> dict[str, Any]:
    require(Permission.PROJECT_DELETE, approvals)
    agent = _agent(db, project_id, agent_id)

    dependencies: list[str] = []
    if db.scalar(
        select(MultiAgentParticipantRecord.id)
        .where(MultiAgentParticipantRecord.agent_id == agent_id)
        .limit(1)
    ):
        dependencies.append("multi-agent task history")
    if db.scalar(
        select(MultiAgentMessageRecord.id)
        .where(MultiAgentMessageRecord.agent_id == agent_id)
        .limit(1)
    ):
        dependencies.append("multi-agent messages")
    if db.scalar(
        select(WorkflowNodeRecord.id)
        .where(WorkflowNodeRecord.agent_id == agent_id)
        .limit(1)
    ):
        dependencies.append("workflow stages")
    if db.scalar(
        select(WorkflowRunStepRecord.id)
        .where(WorkflowRunStepRecord.agent_id == agent_id)
        .limit(1)
    ):
        dependencies.append("workflow run history")

    if dependencies:
        raise ValueError(
            "Agent cannot be deleted because it is referenced by: "
            + ", ".join(sorted(set(dependencies)))
            + ". Remove or replace those references first."
        )

    db.execute(
        delete(AgentToolRecord).where(
            AgentToolRecord.agent_id == agent_id
        )
    )
    agent_name = agent.name
    db.delete(agent)
    db.commit()
    events.emit(
        "agent.deleted",
        agent_id=agent_id,
        project_id=project_id,
        agent_name=agent_name,
        source="executive_api",
    )
    return {
        "deleted": True,
        "id": agent_id,
        "name": agent_name,
    }
