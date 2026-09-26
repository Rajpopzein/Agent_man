from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.tools.registry import (
    TOOL_DEFINITIONS,
    catalog_for_prompt,
)
from app.tools.service import allowed_main_agent_tool_names


@dataclass(frozen=True)
class ExecutiveToolAccess:
    project_id: str
    names: tuple[str, ...]
    catalog: str

    @property
    def count(self) -> int:
        return len(self.names)

    def as_dict(self) -> dict[str, Any]:
        definition_by_name = {
            definition.name: definition
            for definition in TOOL_DEFINITIONS
        }
        return {
            "project_id": self.project_id,
            "count": self.count,
            "tools": [
                {
                    "name": name,
                    "category": definition_by_name[name].category,
                    "risk": definition_by_name[name].risk,
                    "description": definition_by_name[name].description,
                }
                for name in self.names
                if name in definition_by_name
            ],
        }


def executive_tool_access(
    db: Session,
    project_id: str,
) -> ExecutiveToolAccess:
    names = tuple(
        sorted(
            allowed_main_agent_tool_names(
                db,
                project_id,
            )
        )
    )
    return ExecutiveToolAccess(
        project_id=project_id,
        names=names,
        catalog=catalog_for_prompt(set(names)),
    )
