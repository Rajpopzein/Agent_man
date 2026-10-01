import json
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.persistence.models import (
    AgentRecord,
    AgentSkillRecord,
    ConnectorRecord,
    SkillRecord,
)


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9-]+", "-", value.strip().lower())
    normalized = re.sub(r"-+", "-", normalized).strip("-")
    if not normalized:
        raise ValueError("Skill slug must contain letters or numbers")
    return normalized[:160]


def list_skills(db: Session, project_id: str) -> dict[str, Any]:
    rows = db.scalars(
        select(SkillRecord)
        .where(SkillRecord.project_id == project_id)
        .order_by(SkillRecord.name)
    ).all()
    return {
        "skills": [
            {
                "id": row.id,
                "name": row.name,
                "slug": row.slug,
                "description": row.description,
            }
            for row in rows
        ]
    }


def create_skill(
    db: Session,
    project_id: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    name = str(arguments.get("name", "")).strip()
    slug = _slug(str(arguments.get("slug") or name))
    content = str(arguments.get("content", "")).strip()
    if not name or not content:
        raise ValueError("Skill name and SKILL.md content are required")
    existing = db.scalar(
        select(SkillRecord.id).where(
            SkillRecord.project_id == project_id,
            SkillRecord.slug == slug,
        )
    )
    if existing:
        raise ValueError("Skill slug already exists in this project")
    row = SkillRecord(
        project_id=project_id,
        name=name,
        slug=slug,
        description=str(arguments.get("description", "")).strip(),
        content=content,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {
        "skill": {
            "id": row.id,
            "name": row.name,
            "slug": row.slug,
            "description": row.description,
        }
    }


def assign_skill(
    db: Session,
    project_id: str,
    agent_id: str,
    skill_id: str,
) -> dict[str, Any]:
    agent = db.get(AgentRecord, agent_id)
    skill = db.get(SkillRecord, skill_id)
    if agent is None or agent.project_id != project_id:
        raise LookupError("Worker agent not found in this project")
    if skill is None or skill.project_id != project_id:
        raise LookupError("Skill not found in this project")
    row = db.get(
        AgentSkillRecord,
        {"agent_id": agent_id, "skill_id": skill_id},
    )
    if row is None:
        db.add(AgentSkillRecord(agent_id=agent_id, skill_id=skill_id))
        db.commit()
    return {
        "assigned": True,
        "agent_id": agent_id,
        "agent_name": agent.name,
        "skill_id": skill_id,
        "skill_name": skill.name,
    }


def list_connectors(db: Session, project_id: str) -> dict[str, Any]:
    rows = db.scalars(
        select(ConnectorRecord)
        .where(ConnectorRecord.project_id == project_id)
        .order_by(ConnectorRecord.name)
    ).all()
    result = []
    for row in rows:
        try:
            config = json.loads(row.config_json or "{}")
        except json.JSONDecodeError:
            config = {}
        if not isinstance(config, dict):
            config = {}
        result.append({
            "id": row.id,
            "name": row.name,
            "kind": row.kind,
            "base_url": row.base_url,
            "config": config,
            "enabled": row.enabled,
            "has_secret": row.has_secret,
        })
    return {"connectors": result}


def create_connector(
    db: Session,
    project_id: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    name = str(arguments.get("name", "")).strip()
    kind = str(arguments.get("kind", "")).strip().lower()
    if not name or not kind:
        raise ValueError("Connector name and kind are required")
    config = arguments.get("config") or {}
    if not isinstance(config, dict):
        raise ValueError("Connector config must be an object")
    row = ConnectorRecord(
        project_id=project_id,
        name=name,
        kind=kind,
        base_url=str(arguments.get("base_url", "")).strip(),
        config_json=json.dumps(config, ensure_ascii=False),
        enabled=True,
        has_secret=False,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {
        "connector": {
            "id": row.id,
            "name": row.name,
            "kind": row.kind,
            "base_url": row.base_url,
            "enabled": row.enabled,
            "has_secret": False,
        },
        "note": (
            "Connector metadata created. Add credentials through the Extensions "
            "UI so secrets remain outside model/tool results."
        ),
    }
