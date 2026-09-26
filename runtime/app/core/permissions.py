from enum import StrEnum


class Permission(StrEnum):
    PROJECT_READ = "project.files.read"
    PROJECT_WRITE = "project.files.write"
    PROJECT_DELETE = "project.files.delete"
    TERMINAL_EXECUTE = "terminal.execute"
    LOCAL_PORTS = "local.ports"
    OUTSIDE_WORKSPACE = "filesystem.outside_workspace"


class Decision(StrEnum):
    ALLOW = "allow"
    ASK = "ask"
    BLOCK = "block"


DEFAULT_POLICY: dict[Permission, Decision] = {
    Permission.PROJECT_READ: Decision.ALLOW,
    Permission.PROJECT_WRITE: Decision.ALLOW,
    Permission.PROJECT_DELETE: Decision.ASK,
    Permission.TERMINAL_EXECUTE: Decision.ASK,
    Permission.LOCAL_PORTS: Decision.ALLOW,
    Permission.OUTSIDE_WORKSPACE: Decision.BLOCK,
}


class ApprovalRequired(PermissionError):
    def __init__(self, permission: Permission):
        super().__init__(f"Approval required for {permission.value}")
        self.permission = permission


class PermissionDenied(PermissionError):
    pass


def require(permission: Permission, approvals: set[str] | None = None) -> None:
    decision = DEFAULT_POLICY[permission]
    approvals = approvals or set()
    if decision is Decision.ALLOW:
        return
    if decision is Decision.BLOCK:
        raise PermissionDenied(f"Permission blocked: {permission.value}")
    if permission.value not in approvals:
        raise ApprovalRequired(permission)
