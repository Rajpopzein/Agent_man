from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import AgentToolView, ToolToggle, ToolView
from app.persistence.database import get_session
from app.persistence.models import AgentRecord, AgentToolRecord, ToolRecord
from app.tools.service import ensure_agent_defaults, sync_builtin_tools

router = APIRouter(prefix="/api/tools", tags=["tools"])


@router.get("", response_model=list[ToolView])
def list_tools(db: Session = Depends(get_session)):
    sync_builtin_tools(db)
    rows = db.scalars(
        select(ToolRecord).order_by(
            ToolRecord.category,
            ToolRecord.name,
        )
    ).all()
    return [
        ToolView(
            name=row.name,
            description=row.description,
            category=row.category,
            risk=row.risk,
            version=row.version,
            builtin=row.builtin,
            enabled=row.enabled,
        )
        for row in rows
    ]


@router.patch("/{tool_name}", response_model=ToolView)
def update_tool(
    tool_name: str,
    body: ToolToggle,
    db: Session = Depends(get_session),
):
    sync_builtin_tools(db)
    row = db.get(ToolRecord, tool_name)
    if row is None:
        raise HTTPException(404, "Tool not found")
    row.enabled = body.enabled
    db.commit()
    db.refresh(row)
    return ToolView(
        name=row.name,
        description=row.description,
        category=row.category,
        risk=row.risk,
        version=row.version,
        builtin=row.builtin,
        enabled=row.enabled,
    )


@router.get(
    "/agents/{agent_id}",
    response_model=list[AgentToolView],
)
def agent_tools(
    agent_id: str,
    db: Session = Depends(get_session),
):
    if db.get(AgentRecord, agent_id) is None:
        raise HTTPException(404, "Agent not found")

    ensure_agent_defaults(db, agent_id)

    assignments = {
        row.tool_name: row
        for row in db.scalars(
            select(AgentToolRecord).where(
                AgentToolRecord.agent_id == agent_id
            )
        ).all()
    }
    rows = db.scalars(
        select(ToolRecord).order_by(
            ToolRecord.category,
            ToolRecord.name,
        )
    ).all()

    return [
        AgentToolView(
            name=row.name,
            description=row.description,
            category=row.category,
            risk=row.risk,
            version=row.version,
            globally_enabled=row.enabled,
            assigned=bool(
                assignments.get(row.name)
                and assignments[row.name].enabled
            ),
        )
        for row in rows
    ]


@router.put(
    "/agents/{agent_id}/{tool_name}",
    response_model=AgentToolView,
)
def set_agent_tool(
    agent_id: str,
    tool_name: str,
    body: ToolToggle,
    db: Session = Depends(get_session),
):
    if db.get(AgentRecord, agent_id) is None:
        raise HTTPException(404, "Agent not found")

    sync_builtin_tools(db)
    tool = db.get(ToolRecord, tool_name)
    if tool is None:
        raise HTTPException(404, "Tool not found")

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
            enabled=body.enabled,
        )
        db.add(assignment)
    else:
        assignment.enabled = body.enabled

    db.commit()

    return AgentToolView(
        name=tool.name,
        description=tool.description,
        category=tool.category,
        risk=tool.risk,
        version=tool.version,
        globally_enabled=tool.enabled,
        assigned=assignment.enabled,
    )
