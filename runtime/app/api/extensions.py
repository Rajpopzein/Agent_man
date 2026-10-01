import json
import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.api.schemas import (
    ConnectorCreate,
    ConnectorUpdate,
    ConnectorView,
    SkillCreate,
    SkillUpdate,
    SkillView,
)
from app.core.secrets import secrets
from app.persistence.database import get_session
from app.persistence.models import (
    AgentRecord,
    AgentSkillRecord,
    ConnectorRecord,
    ProjectRecord,
    SkillRecord,
)

router = APIRouter(prefix="/api/extensions", tags=["extensions"])


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9-]+", "-", value.strip().lower())
    normalized = re.sub(r"-+", "-", normalized).strip("-")
    if not normalized:
        raise ValueError("Skill slug must contain letters or numbers")
    return normalized[:160]


def _skill_view(row: SkillRecord) -> SkillView:
    return SkillView(
        id=row.id,
        project_id=row.project_id,
        name=row.name,
        slug=row.slug,
        description=row.description,
        content=row.content,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _connector_view(row: ConnectorRecord) -> ConnectorView:
    try:
        config = json.loads(row.config_json or "{}")
    except json.JSONDecodeError:
        config = {}
    if not isinstance(config, dict):
        config = {}
    return ConnectorView(
        id=row.id,
        project_id=row.project_id,
        name=row.name,
        kind=row.kind,
        base_url=row.base_url,
        config=config,
        enabled=row.enabled,
        has_secret=row.has_secret,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("/projects/{project_id}/skills", response_model=list[SkillView])
def list_skills(project_id: str, db: Session = Depends(get_session)):
    if db.get(ProjectRecord, project_id) is None:
        raise HTTPException(404, "Project not found")
    rows = db.scalars(
        select(SkillRecord)
        .where(SkillRecord.project_id == project_id)
        .order_by(SkillRecord.name)
    ).all()
    return [_skill_view(row) for row in rows]


@router.post("/projects/{project_id}/skills", response_model=SkillView, status_code=201)
def create_skill(
    project_id: str,
    body: SkillCreate,
    db: Session = Depends(get_session),
):
    if db.get(ProjectRecord, project_id) is None:
        raise HTTPException(404, "Project not found")
    slug = _slug(body.slug)
    existing = db.scalar(
        select(SkillRecord.id).where(
            SkillRecord.project_id == project_id,
            SkillRecord.slug == slug,
        )
    )
    if existing:
        raise HTTPException(409, "Skill slug already exists in this project")
    row = SkillRecord(
        project_id=project_id,
        name=body.name.strip(),
        slug=slug,
        description=body.description.strip(),
        content=body.content.strip(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _skill_view(row)


@router.patch("/skills/{skill_id}", response_model=SkillView)
def update_skill(
    skill_id: str,
    body: SkillUpdate,
    db: Session = Depends(get_session),
):
    row = db.get(SkillRecord, skill_id)
    if row is None:
        raise HTTPException(404, "Skill not found")
    if body.name is not None:
        row.name = body.name.strip()
    if body.slug is not None:
        row.slug = _slug(body.slug)
    if body.description is not None:
        row.description = body.description.strip()
    if body.content is not None:
        row.content = body.content.strip()
    db.commit()
    db.refresh(row)
    return _skill_view(row)


@router.delete("/skills/{skill_id}")
def delete_skill(skill_id: str, db: Session = Depends(get_session)):
    row = db.get(SkillRecord, skill_id)
    if row is None:
        raise HTTPException(404, "Skill not found")
    db.execute(
        delete(AgentSkillRecord).where(AgentSkillRecord.skill_id == skill_id)
    )
    db.delete(row)
    db.commit()
    return {"deleted": True, "id": skill_id}


@router.get("/agents/{agent_id}/skills", response_model=list[SkillView])
def agent_skills(agent_id: str, db: Session = Depends(get_session)):
    if db.get(AgentRecord, agent_id) is None:
        raise HTTPException(404, "Agent not found")
    rows = db.scalars(
        select(SkillRecord)
        .join(AgentSkillRecord, AgentSkillRecord.skill_id == SkillRecord.id)
        .where(AgentSkillRecord.agent_id == agent_id)
        .order_by(SkillRecord.name)
    ).all()
    return [_skill_view(row) for row in rows]


@router.put("/agents/{agent_id}/skills/{skill_id}")
def assign_skill(
    agent_id: str,
    skill_id: str,
    db: Session = Depends(get_session),
):
    agent = db.get(AgentRecord, agent_id)
    skill = db.get(SkillRecord, skill_id)
    if agent is None:
        raise HTTPException(404, "Agent not found")
    if skill is None or skill.project_id != agent.project_id:
        raise HTTPException(404, "Skill not found in this project")
    row = db.get(
        AgentSkillRecord,
        {"agent_id": agent_id, "skill_id": skill_id},
    )
    if row is None:
        db.add(AgentSkillRecord(agent_id=agent_id, skill_id=skill_id))
        db.commit()
    return {"assigned": True, "agent_id": agent_id, "skill_id": skill_id}


@router.delete("/agents/{agent_id}/skills/{skill_id}")
def unassign_skill(
    agent_id: str,
    skill_id: str,
    db: Session = Depends(get_session),
):
    row = db.get(
        AgentSkillRecord,
        {"agent_id": agent_id, "skill_id": skill_id},
    )
    if row is not None:
        db.delete(row)
        db.commit()
    return {"assigned": False, "agent_id": agent_id, "skill_id": skill_id}


@router.get("/projects/{project_id}/connectors", response_model=list[ConnectorView])
def list_connectors(project_id: str, db: Session = Depends(get_session)):
    if db.get(ProjectRecord, project_id) is None:
        raise HTTPException(404, "Project not found")
    rows = db.scalars(
        select(ConnectorRecord)
        .where(ConnectorRecord.project_id == project_id)
        .order_by(ConnectorRecord.name)
    ).all()
    return [_connector_view(row) for row in rows]


@router.post("/projects/{project_id}/connectors", response_model=ConnectorView, status_code=201)
def create_connector(
    project_id: str,
    body: ConnectorCreate,
    db: Session = Depends(get_session),
):
    if db.get(ProjectRecord, project_id) is None:
        raise HTTPException(404, "Project not found")
    row = ConnectorRecord(
        project_id=project_id,
        name=body.name.strip(),
        kind=body.kind.strip().lower(),
        base_url=body.base_url.strip(),
        config_json=json.dumps(body.config, ensure_ascii=False),
        enabled=True,
        has_secret=False,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    if body.api_key:
        secrets.set("connector:" + row.id + ":api_key", body.api_key)
        row.has_secret = True
        db.commit()
        db.refresh(row)
    return _connector_view(row)


@router.patch("/connectors/{connector_id}", response_model=ConnectorView)
def update_connector(
    connector_id: str,
    body: ConnectorUpdate,
    db: Session = Depends(get_session),
):
    row = db.get(ConnectorRecord, connector_id)
    if row is None:
        raise HTTPException(404, "Connector not found")
    if body.name is not None:
        row.name = body.name.strip()
    if body.kind is not None:
        row.kind = body.kind.strip().lower()
    if body.base_url is not None:
        row.base_url = body.base_url.strip()
    if body.config is not None:
        row.config_json = json.dumps(body.config, ensure_ascii=False)
    if body.enabled is not None:
        row.enabled = body.enabled
    if body.clear_secret:
        secrets.delete("connector:" + row.id + ":api_key")
        row.has_secret = False
    if body.api_key:
        secrets.set("connector:" + row.id + ":api_key", body.api_key)
        row.has_secret = True
    db.commit()
    db.refresh(row)
    return _connector_view(row)


@router.delete("/connectors/{connector_id}")
def delete_connector(
    connector_id: str,
    db: Session = Depends(get_session),
):
    row = db.get(ConnectorRecord, connector_id)
    if row is None:
        raise HTTPException(404, "Connector not found")
    secrets.delete("connector:" + row.id + ":api_key")
    db.delete(row)
    db.commit()
    return {"deleted": True, "id": connector_id}
