from sqlalchemy.orm import Session

from app.tools.service import allowed_tool_names

CAPABILITY_TOOLS: dict[str, tuple[str, ...]] = {
    "internet": ("http_get",),
    "web": ("http_get",),
    "adb": ("adb_status", "adb_install", "adb_devices"),
    "android": ("adb_status", "adb_install", "adb_devices"),
    "android_device": ("adb_status", "adb_install", "adb_devices"),
    "serial": (
        "list_serial_ports",
        "serial_open",
        "serial_list_sessions",
        "serial_read",
        "serial_write",
        "serial_close",
    ),
    "hardware": (
        "list_serial_ports",
        "serial_open",
        "serial_list_sessions",
        "serial_read",
        "serial_write",
        "serial_close",
    ),
    "com": (
        "list_serial_ports",
        "serial_open",
        "serial_list_sessions",
        "serial_read",
        "serial_write",
        "serial_close",
    ),
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

    adb_terms = (
        "adb",
        "android debug bridge",
        "android device",
        "usb debugging",
        "platform tools",
        "platform-tools",
    )
    adb_missing_terms = missing_terms + (
        "couldn't install",
        "could not install",
        "can't install",
        "cannot install",
        "unable to install",
        "administrator privileges",
        "admin privileges",
    )
    if (
        any(term in lowered for term in adb_terms)
        and any(term in lowered for term in adb_missing_terms)
    ):
        return "adb"

    hardware_terms = (
        "serial port",
        "com port",
        "hardware access",
        "serial access",
        "usb serial",
    )
    if (
        any(term in lowered for term in hardware_terms)
        and any(term in lowered for term in missing_terms)
    ):
        return "serial"
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
