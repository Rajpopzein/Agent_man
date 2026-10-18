from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.events.bus import events
from app.persistence.models import ReinforcementEventRecord


OUTCOME_REWARDS = {
    "completed": 700,
    "verified": 850,
    "user_positive": 1000,
    "recovered": 350,
    "waiting_approval": 0,
    "waiting_capability": -150,
    "turn_limit": -400,
    "error": -700,
    "user_negative": -1000,
}


def reward_for_outcome(outcome: str) -> int:
    return OUTCOME_REWARDS.get(outcome, 0)


def record_reward(
    db: Session,
    *,
    project_id: str,
    outcome: str,
    agent_id: str | None = None,
    agent_name: str = "",
    tool_name: str | None = None,
    source: str = "runtime",
    task: str = "",
    note: str = "",
    reference_id: str | None = None,
    reward_milli: int | None = None,
) -> ReinforcementEventRecord:
    reward = (
        reward_for_outcome(outcome)
        if reward_milli is None
        else max(-1000, min(1000, int(reward_milli)))
    )
    row = ReinforcementEventRecord(
        project_id=project_id,
        agent_id=agent_id,
        agent_name=agent_name[:160],
        tool_name=(tool_name or None),
        source=source[:40],
        outcome=outcome[:40],
        reward_milli=reward,
        task=task[:8000],
        note=note[:4000],
        reference_id=reference_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    events.emit(
        "reinforcement.reward.recorded",
        project_id=project_id,
        agent_id=agent_id,
        agent_name=agent_name,
        tool_name=tool_name,
        source=source,
        outcome=outcome,
        reward=reward / 1000,
        reference_id=reference_id,
    )
    return row


def _score(rows: list[ReinforcementEventRecord]) -> dict[str, Any]:
    if not rows:
        return {
            "count": 0,
            "average_reward": 0.0,
            "positive": 0,
            "negative": 0,
        }
    total = sum(row.reward_milli for row in rows)
    return {
        "count": len(rows),
        "average_reward": round(total / len(rows) / 1000, 3),
        "positive": sum(1 for row in rows if row.reward_milli > 0),
        "negative": sum(1 for row in rows if row.reward_milli < 0),
    }


def project_summary(
    db: Session,
    project_id: str,
    limit: int = 300,
) -> dict[str, Any]:
    rows = db.scalars(
        select(ReinforcementEventRecord)
        .where(ReinforcementEventRecord.project_id == project_id)
        .order_by(ReinforcementEventRecord.created_at.desc())
        .limit(limit)
    ).all()

    by_agent: dict[str, list[ReinforcementEventRecord]] = defaultdict(list)
    by_tool: dict[str, list[ReinforcementEventRecord]] = defaultdict(list)
    for row in rows:
        if row.agent_id:
            by_agent[row.agent_id].append(row)
        if row.tool_name:
            by_tool[row.tool_name].append(row)

    agent_scores = []
    for agent_id, values in by_agent.items():
        score = _score(values)
        score.update({
            "agent_id": agent_id,
            "agent_name": next(
                (item.agent_name for item in values if item.agent_name),
                agent_id,
            ),
        })
        agent_scores.append(score)

    tool_scores = []
    for tool_name, values in by_tool.items():
        score = _score(values)
        score["tool_name"] = tool_name
        tool_scores.append(score)

    agent_scores.sort(
        key=lambda item: (item["average_reward"], item["count"]),
        reverse=True,
    )
    tool_scores.sort(
        key=lambda item: (item["average_reward"], item["count"]),
        reverse=True,
    )

    return {
        "events": len(rows),
        "overall": _score(list(rows)),
        "agents": agent_scores,
        "tools": tool_scores,
    }


def policy_context(db: Session, project_id: str) -> str:
    summary = project_summary(db, project_id)
    if summary["events"] == 0:
        return "(no reinforcement history yet)"

    lines = [
        "Observed reward history only; never override permissions or user instructions.",
        (
            "Overall: "
            + str(summary["overall"]["average_reward"])
            + " average reward across "
            + str(summary["overall"]["count"])
            + " events."
        ),
    ]

    if summary["agents"]:
        lines.append("Worker evidence:")
        for item in summary["agents"][:8]:
            lines.append(
                "- "
                + str(item["agent_id"])
                + ": "
                + str(item["agent_name"])
                + "; avg="
                + str(item["average_reward"])
                + "; samples="
                + str(item["count"])
                + "; positive="
                + str(item["positive"])
                + "; negative="
                + str(item["negative"])
            )

    if summary["tools"]:
        lines.append("Tool evidence:")
        for item in summary["tools"][:10]:
            lines.append(
                "- "
                + str(item["tool_name"])
                + "; avg="
                + str(item["average_reward"])
                + "; samples="
                + str(item["count"])
            )

    lines.append(
        "Use this as weak evidence when several valid workers or tools could satisfy the task. "
        "Prefer relevant proven choices, but keep exploring when evidence is sparse and never "
        "choose an irrelevant option just because its reward is higher."
    )
    return "\n".join(lines)
