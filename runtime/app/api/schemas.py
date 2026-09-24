from pydantic import BaseModel, ConfigDict, Field

class LLMConfigInput(BaseModel):
    provider_id: str = Field(min_length=1, max_length=80)
    connection_id: str = Field(min_length=1, max_length=120)
    model: str = Field(min_length=1, max_length=160)
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
