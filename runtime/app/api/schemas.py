from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AIProviderView(BaseModel):
    id: str
    label: str
    default_endpoint: str | None
    requires_api_key: bool
    local: bool


class AIConnectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    provider_id: str = Field(min_length=1, max_length=80)
    endpoint: str | None = Field(default=None, max_length=512)
    default_model: str | None = Field(default=None, max_length=160)
    api_key: str | None = Field(default=None, max_length=4096)


class AIConnectionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    endpoint: str | None = Field(default=None, max_length=512)
    default_model: str | None = Field(default=None, max_length=160)
    api_key: str | None = Field(default=None, max_length=4096)
    clear_secret: bool = False


class AIConnectionView(BaseModel):
    id: str
    name: str
    provider_id: str
    endpoint: str | None
    default_model: str | None
    has_secret: bool


class AIConnectionTestView(BaseModel):
    ok: bool
    provider_id: str
    endpoint: str | None
    models: list[str]


class LLMConfigInput(BaseModel):
    provider_id: str = Field(min_length=1, max_length=80)
    connection_id: str = Field(min_length=1, max_length=120)
    model: str = Field(min_length=1, max_length=160)
    endpoint: str | None = Field(default=None, max_length=512)
    context_limit: int | None = Field(default=None, ge=256)
    temperature: float = Field(default=0.2, ge=0, le=2)
    cloud_fallback_allowed: bool = False


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    workspace_path: str = Field(min_length=1, max_length=1024)


class ProjectView(ProjectCreate):
    model_config = ConfigDict(from_attributes=True)
    id: str


class AgentCreate(BaseModel):
    project_id: str
    name: str = Field(min_length=1, max_length=120)
    role: str = Field(min_length=1, max_length=120)
    llm: LLMConfigInput


class AgentView(BaseModel):
    id: str
    project_id: str
    name: str
    role: str
    state: str
    llm: LLMConfigInput


class AgentPrompt(BaseModel):
    prompt: str = Field(min_length=1, max_length=20_000)
    endpoint: str | None = Field(default=None, max_length=512)


class AgentReply(BaseModel):
    agent_id: str
    text: str


class AgentRunRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=20_000)
    endpoint: str | None = Field(default=None, max_length=512)
    allow_terminal: bool = False
    allow_delete: bool = False


class AgentRunReply(BaseModel):
    agent_id: str
    status: str
    text: str
    steps: list[dict[str, Any]]


class MultiAgentTaskCreate(BaseModel):
    project_id: str
    title: str = Field(min_length=1, max_length=160)
    prompt: str = Field(min_length=1, max_length=30_000)
    agent_ids: list[str] = Field(min_length=2, max_length=8)
    max_rounds: int = Field(default=3, ge=1, le=8)


class MultiAgentRunRequest(BaseModel):
    allow_terminal: bool = False
    allow_delete: bool = False


class MultiAgentParticipantView(BaseModel):
    agent_id: str
    agent_name: str
    role: str
    position: int
    status: str
    last_round: int


class MultiAgentMessageView(BaseModel):
    id: str
    agent_id: str | None
    agent_name: str
    kind: str
    round_number: int
    content: str
    created_at: datetime


class MultiAgentTaskView(BaseModel):
    id: str
    project_id: str
    title: str
    prompt: str
    status: str
    max_rounds: int
    current_round: int
    created_at: datetime
    completed_at: datetime | None
    participants: list[MultiAgentParticipantView]
    messages: list[MultiAgentMessageView]


class ToolView(BaseModel):
    name: str
    description: str
    category: str
    risk: str
    version: str
    builtin: bool
    enabled: bool


class ToolToggle(BaseModel):
    enabled: bool


class AgentToolView(BaseModel):
    name: str
    description: str
    category: str
    risk: str
    version: str
    globally_enabled: bool
    assigned: bool
