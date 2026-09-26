from sqlalchemy.orm import Session

from app.tools.service import allowed_tool_names

CAPABILITY_TOOLS: dict[str, tuple[str, ...]] = {
    "internet": ("http_get",),
    "web": ("http_get",),
}


def detect_missing_capability(text: str) -> str | None:
    lowered = text.lower()
    internet_terms = (
        "internet",
        "web access",
        "browse the web",
        "access the web",
        "online access",
    )
    missing_terms = (
        "don't have access",
        "do not have access",
        "no access",
        "can't access",
        "cannot access",
        "unable to access",
        "don't have internet",
        "do not have internet",
        "no internet",
    )
    if (
        any(term in lowered for term in internet_terms)
        and any(term in lowered for term in missing_terms)
    ):
        return "internet"
    return None


def resolve_capability(
    db: Session,
    agent_id: str,
    capability: str,
) -> list[str]:
    normalized = capability.strip().lower()
    candidates = CAPABILITY_TOOLS.get(normalized, ())
    if not candidates:
        return []

    allowed = allowed_tool_names(db, agent_id)
    return [
        tool_name
        for tool_name in candidates
        if tool_name in allowed
    ]
