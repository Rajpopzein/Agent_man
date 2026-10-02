from sqlalchemy import select
from sqlalchemy.orm import Session

from app.persistence.models import AgentSkillRecord, SkillRecord


def assigned_skill_context(db: Session, agent_id: str) -> str:
    rows = db.scalars(
        select(SkillRecord)
        .join(AgentSkillRecord, AgentSkillRecord.skill_id == SkillRecord.id)
        .where(AgentSkillRecord.agent_id == agent_id)
        .order_by(SkillRecord.name)
    ).all()
    if not rows:
        return "(no assigned skills)"

    blocks = []
    for row in rows:
        blocks.append(
            "### SKILL.md: "
            + row.slug
            + "\n"
            + "# "
            + row.name
            + "\n"
            + (row.description.strip() + "\n\n" if row.description.strip() else "")
            + row.content.strip()
        )
    return "\n\n".join(blocks)
