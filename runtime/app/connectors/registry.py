from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ConnectorCapability:
    name: str
    description: str
    risk: str = "read"


@dataclass(frozen=True)
class ConnectorAdapter:
    kind: str
    label: str
    description: str
    capabilities: tuple[ConnectorCapability, ...]
    setup_notes: str


ADAPTERS = {
    "generic-http": ConnectorAdapter(
        kind="generic-http",
        label="Generic HTTP API",
        description=(
            "Template for a documented HTTP API. Add a dedicated adapter "
            "before exposing connector actions to agents."
        ),
        capabilities=(),
        setup_notes=(
            "Configure base URL and credentials. No arbitrary connector HTTP "
            "actions are enabled by default."
        ),
    ),
    "groww": ConnectorAdapter(
        kind="groww",
        label="Groww",
        description=(
            "Groww connector template for portfolio/investment workflows. "
            "The adapter intentionally defines no live actions until a "
            "documented API/auth contract is configured."
        ),
        capabilities=(),
        setup_notes=(
            "Supply the official API/authentication contract and approved "
            "actions before enabling account data or transaction operations."
        ),
    ),
}


def connector_catalog() -> list[dict[str, Any]]:
    return [
        {
            "kind": adapter.kind,
            "label": adapter.label,
            "description": adapter.description,
            "capabilities": [
                {
                    "name": capability.name,
                    "description": capability.description,
                    "risk": capability.risk,
                }
                for capability in adapter.capabilities
            ],
            "setup_notes": adapter.setup_notes,
        }
        for adapter in ADAPTERS.values()
    ]


def adapter_for(kind: str) -> ConnectorAdapter | None:
    return ADAPTERS.get(kind.strip().lower())
