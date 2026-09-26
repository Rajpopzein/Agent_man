from fastapi import APIRouter, Depends, Query
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.api.schemas import LLMLogView
from app.persistence.database import get_session
from app.persistence.models import LLMLogRecord

router = APIRouter(prefix="/api/llm-logs", tags=["llm-logs"])


@router.get(
    "/projects/{project_id}",
    response_model=list[LLMLogView],
)
def list_logs(
    project_id: str,
    limit: int = Query(default=200, ge=1, le=1000),
    db: Session = Depends(get_session),
):
    rows = db.scalars(
        select(LLMLogRecord)
        .where(LLMLogRecord.project_id == project_id)
        .order_by(LLMLogRecord.created_at.desc())
        .limit(limit)
    ).all()
    return rows


@router.delete("/projects/{project_id}")
def clear_logs(
    project_id: str,
    db: Session = Depends(get_session),
):
    result = db.execute(
        delete(LLMLogRecord).where(
            LLMLogRecord.project_id == project_id
        )
    )
    db.commit()
    return {"cleared": True, "count": result.rowcount or 0}
