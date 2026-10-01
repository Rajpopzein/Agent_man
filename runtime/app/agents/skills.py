from sqlalchemy import select
from sqlalchemy.orm import Session

from app.persistence.models import AgentSkillRecord, SkillRecord


def assigned_skill_context(
    db: Session,
    agent_id: str,
    *,
    max_chars: int | None = None,
) -> str:
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
        block = (
            "### SKILL.md: "
            + row.slug
            + "\n"
            + "# "
            + row.name
            + "\n"
            + (row.description.strip() + "\n\n" if row.description.strip() else "")
            + row.content.strip()
        )
        blocks.append(block)

    combined = "\n\n".join(blocks)
    if max_chars is None or max_chars <= 0 or len(combined) <= max_chars:
        return combined

    per_skill = max(800, max_chars // max(1, len(blocks)))
    compacted: list[str] = []
    for block in blocks:
        if len(block) <= per_skill:
            compacted.append(block)
            continue
        marker = "\n...[skill content compacted by runtime]..."
        keep = max(200, per_skill - len(marker))
        compacted.append(
            block[: int(keep * 0.7)]
            + marker
            + block[-(keep - int(keep * 0.7)) :]
        )

    result = "\n\n".join(compacted)
    if len(result) <= max_chars:
        return result

    marker = "\n...[additional assigned skill context omitted]..."
    return result[: max(0, max_chars - len(marker))] + marker
