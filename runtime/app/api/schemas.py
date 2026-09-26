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
    allow_network: bool = False


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
    max_rounds: int = Field(default=12, ge=2, le=30)


class MultiAgentRunRequest(BaseModel):
    allow_terminal: bool = False
    allow_delete: bool = False
    allow_network: bool = False
    extend_rounds: int = Field(default=0, ge=0, le=20)


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


class WorkflowNodeInput(BaseModel):
    key: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=160)
    agent_id: str
    instructions: str = Field(min_length=1, max_length=20_000)
    on_success_key: str | None = Field(default=None, max_length=80)
    on_failure_key: str | None = Field(default=None, max_length=80)
    max_retries: int = Field(default=0, ge=0, le=5)


class WorkflowCreate(BaseModel):
    project_id: str
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=2000)
    nodes: list[WorkflowNodeInput] = Field(min_length=1, max_length=20)


class WorkflowNodeView(BaseModel):
    id: str
    key: str
    name: str
    agent_id: str
    agent_name: str
    role: str
    instructions: str
    position: int
    on_success_key: str | None
    on_failure_key: str | None
    max_retries: int


class WorkflowView(BaseModel):
    id: str
    project_id: str
    name: str
    description: str
    start_node_id: str | None
    created_at: datetime
    nodes: list[WorkflowNodeView]


class WorkflowRunRequest(BaseModel):
    input_prompt: str = Field(min_length=1, max_length=30_000)
    allow_terminal: bool = False
    allow_delete: bool = False
    allow_network: bool = False


class WorkflowRunStepView(BaseModel):
    id: str
    node_id: str
    node_name: str
    agent_id: str
    agent_name: str
    attempt: int
    status: str
    outcome: str | None
    output_text: str
    created_at: datetime


class WorkflowRunView(BaseModel):
    id: str
    workflow_id: str
    project_id: str
    status: str
    current_node_id: str | None
    input_prompt: str
    last_output: str
    step_count: int
    created_at: datetime
    completed_at: datetime | None
    steps: list[WorkflowRunStepView]


class MainAgentConfigInput(BaseModel):
    connection_id: str = Field(min_length=1, max_length=120)
    model: str = Field(min_length=1, max_length=160)
    context_limit: int | None = Field(default=None, ge=256)
    temperature: float = Field(default=0.2, ge=0, le=2)


class MainAgentConfigView(BaseModel):
    project_id: str
    connection_id: str
    provider_id: str
    model: str
    endpoint: str | None
    context_limit: int | None
    temperature: float


class MainAgentChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=30_000)
    allow_terminal: bool = False
    allow_delete: bool = False
    allow_network: bool = False


class MainAgentMessageView(BaseModel):
    id: str
    role: str
    content: str
    created_at: datetime


class MainAgentChatReply(BaseModel):
    status: str
    text: str
    steps: list[dict[str, Any]]


class LLMLogView(BaseModel):
    id: str
    project_id: str | None
    actor_id: str | None
    actor_name: str
    actor_role: str
    provider_id: str
    model: str
    endpoint: str | None
    status: str
    duration_ms: int
    request_json: str
    response_text: str
    error_text: str
    created_at: datetime
