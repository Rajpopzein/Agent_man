from sqlalchemy import select
from sqlalchemy.orm import Session

from app.persistence.models import (
    AgentRecord,
    AgentToolRecord,
    MainAgentToolRecord,
    ProjectRecord,
    ToolRecord,
)
from app.tools.registry import TOOL_DEFINITIONS


def sync_builtin_tools(db: Session) -> None:
    existing = {
        row.name: row
        for row in db.scalars(select(ToolRecord)).all()
    }
    for definition in TOOL_DEFINITIONS:
        row = existing.get(definition.name)
        if row is None:
            row = ToolRecord(
                name=definition.name,
                description=definition.description,
                category=definition.category,
                risk=definition.risk,
                version=definition.version,
                builtin=True,
                enabled=True,
            )
            db.add(row)
        else:
            row.description = definition.description
            row.category = definition.category
            row.risk = definition.risk
            row.version = definition.version
            row.builtin = True
    db.commit()


def ensure_agent_defaults(db: Session, agent_id: str) -> None:
    sync_builtin_tools(db)
    existing = {
        row.tool_name
        for row in db.scalars(
            select(AgentToolRecord).where(
                AgentToolRecord.agent_id == agent_id
            )
        ).all()
    }
    enabled_tools = db.scalars(
        select(ToolRecord).where(ToolRecord.enabled.is_(True))
    ).all()
    changed = False
    for tool in enabled_tools:
        if tool.name in existing:
            continue
        db.add(
            AgentToolRecord(
                agent_id=agent_id,
                tool_name=tool.name,
                enabled=True,
            )
        )
        changed = True
    if changed:
        db.commit()


def ensure_main_agent_defaults(
    db: Session,
    project_id: str,
) -> None:
    if db.get(ProjectRecord, project_id) is None:
        return

    sync_builtin_tools(db)
    existing = {
        row.tool_name
        for row in db.scalars(
            select(MainAgentToolRecord).where(
                MainAgentToolRecord.project_id == project_id
            )
        ).all()
    }
    enabled_tools = db.scalars(
        select(ToolRecord).where(ToolRecord.enabled.is_(True))
    ).all()
    changed = False
    for tool in enabled_tools:
        if tool.name in existing:
            continue
        db.add(
            MainAgentToolRecord(
                project_id=project_id,
                tool_name=tool.name,
                enabled=True,
            )
        )
        changed = True
    if changed:
        db.commit()


def globally_enabled_tool_names(db: Session) -> set[str]:
    sync_builtin_tools(db)
    rows = db.execute(
        select(ToolRecord.name).where(
            ToolRecord.enabled.is_(True)
        )
    ).all()
    return {row[0] for row in rows}


def allowed_main_agent_tool_names(
    db: Session,
    project_id: str,
) -> set[str]:
    ensure_main_agent_defaults(db, project_id)
    rows = db.execute(
        select(MainAgentToolRecord.tool_name)
        .join(
            ToolRecord,
            ToolRecord.name == MainAgentToolRecord.tool_name,
        )
        .where(
            MainAgentToolRecord.project_id == project_id,
            MainAgentToolRecord.enabled.is_(True),
            ToolRecord.enabled.is_(True),
        )
    ).all()
    return {row[0] for row in rows}


def allowed_tool_names(db: Session, agent_id: str) -> set[str]:
    agent = db.get(AgentRecord, agent_id)
    if agent is None:
        return set()
    ensure_agent_defaults(db, agent_id)
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
    ).all()
    return {row[0] for row in rows}
