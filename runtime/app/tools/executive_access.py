from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.core.permissions import Permission
from app.tools.registry import (
    TOOL_DEFINITIONS,
    catalog_for_prompt,
)
from app.tools.service import allowed_main_agent_tool_names



_APPROVAL_GATE_BY_TOOL: dict[str, tuple[str, Permission]] = {
    "delete_path": ("delete", Permission.PROJECT_DELETE),
    "run_command": ("exec", Permission.TERMINAL_EXECUTE),
    "git_commit": ("exec", Permission.TERMINAL_EXECUTE),
    "run_tests": ("exec", Permission.TERMINAL_EXECUTE),
    "run_build": ("exec", Permission.TERMINAL_EXECUTE),
    "lint": ("exec", Permission.TERMINAL_EXECUTE),
    "start_process": ("exec", Permission.TERMINAL_EXECUTE),
    "stop_process": ("exec", Permission.TERMINAL_EXECUTE),
    "http_get": ("net", Permission.NETWORK_ACCESS),
    "serial_open": ("hw", Permission.SERIAL_ACCESS),
    "serial_read": ("hw", Permission.SERIAL_ACCESS),
    "serial_write": ("hw", Permission.SERIAL_ACCESS),
}


def _approval_metadata(name: str) -> tuple[str | None, str | None]:
    item = _APPROVAL_GATE_BY_TOOL.get(name)
    if item is None:
        return None, None
    gate, permission = item
    return gate, permission.value


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
                    "approval_gate": _approval_metadata(name)[0],
                    "permission": _approval_metadata(name)[1],
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
