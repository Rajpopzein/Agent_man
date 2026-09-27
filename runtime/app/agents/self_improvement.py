import json
import re
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.persistence.models import SelfUpgradeProposalRecord


UPGRADE_MUTATING_TOOLS = frozenset(
    {
        "write_file",
        "edit_file",
        "delete_path",
        "run_command",
        "git_commit",
        "start_process",
        "stop_process",
    }
)
UPGRADE_VALIDATION_TOOLS = frozenset(
    {"run_tests", "run_build", "lint"}
)

_UPGRADE_INTENT_PHRASES = (
    "self upgrade",
    "self-upgrade",
    "self upgradation",
    "self-upgradation",
    "self improvement",
    "self-improvement",
    "upgrade yourself",
    "improve yourself",
    "upgrade agent man",
    "improve agent man",
)

_UPGRADE_COMMAND = re.compile(
    r"\b(approve|reject|apply)\s+(?:self[-\s]*)?upgrade\s+([0-9a-fA-F-]{6,36})\b",
    re.IGNORECASE,
)


def is_self_upgrade_intent(text: str) -> bool:
    lowered = " ".join(text.lower().split())
    return any(phrase in lowered for phrase in _UPGRADE_INTENT_PHRASES)


def parse_upgrade_command(text: str) -> tuple[str, str] | None:
    match = _UPGRADE_COMMAND.search(text)
    if not match:
        return None
    return match.group(1).lower(), match.group(2).lower()


def find_upgrade(
    db: Session,
    project_id: str,
    token: str,
) -> SelfUpgradeProposalRecord | None:
    normalized = token.strip().lower()
    rows = list(
        db.scalars(
            select(SelfUpgradeProposalRecord)
            .where(SelfUpgradeProposalRecord.project_id == project_id)
            .order_by(SelfUpgradeProposalRecord.created_at.desc())
        ).all()
    )
    exact = [
        row for row in rows
        if row.id.lower() == normalized
    ]
    if exact:
        return exact[0]

    matches = [
        row for row in rows
        if row.id.lower().startswith(normalized)
    ]
    return matches[0] if len(matches) == 1 else None


def normalize_text_list(
    value: object,
    *,
    limit: int = 12,
    item_limit: int = 1000,
) -> list[str]:
    if isinstance(value, str):
        values: Iterable[object] = [value]
    elif isinstance(value, list):
        values = value
    else:
        values = []

    result: list[str] = []
    for item in values:
        text = " ".join(str(item).split()).strip()
        if text:
            result.append(text[:item_limit])
        if len(result) >= limit:
            break
    return result


def decode_text_list(raw: str) -> list[str]:
    try:
        value = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    return normalize_text_list(value)


def upgrade_context(db: Session, project_id: str) -> str:
    rows = list(
        db.scalars(
            select(SelfUpgradeProposalRecord)
            .where(SelfUpgradeProposalRecord.project_id == project_id)
            .order_by(SelfUpgradeProposalRecord.created_at.desc())
            .limit(8)
        ).all()
    )
    if not rows:
        return "(none)"

    lines: list[str] = []
    for row in rows:
        changes = decode_text_list(row.changes_json)
        summary = "; ".join(changes[:3]) or "(no change list)"
        lines.append(
            f"- {row.id}: [{row.status}] {row.title} - {row.reason} "
            f"Changes: {summary}"
        )
    return "\n".join(lines)
