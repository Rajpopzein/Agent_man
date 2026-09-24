from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID, uuid4

class AgentState(StrEnum):
    IDLE="idle"
    THINKING="thinking"
    EXECUTING="executing"
    WAITING="waiting"
    VALIDATING="validating"
    FAILED="failed"

@dataclass
class LLMConfig:
    provider_id: str
    connection_id: str
    model: str
    context_limit: int | None = None
    temperature: float = 0.2

@dataclass
class Agent:
    name: str
    role: str
    llm: LLMConfig
    id: UUID = field(default_factory=uuid4)
    state: AgentState = AgentState.IDLE

@dataclass
class Project:
    name: str
    workspace_path: str
    id: UUID = field(default_factory=uuid4)
