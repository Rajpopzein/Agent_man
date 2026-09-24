from pydantic import BaseModel,ConfigDict,Field
class LLMConfigInput(BaseModel):
 provider_id:str;connection_id:str;model:str;endpoint:str|None=None;context_limit:int|None=Field(default=None,ge=256);temperature:float=Field(default=.2,ge=0,le=2);cloud_fallback_allowed:bool=False
class ProjectCreate(BaseModel):name:str;workspace_path:str
class ProjectView(ProjectCreate):model_config=ConfigDict(from_attributes=True);id:str
class AgentCreate(BaseModel):project_id:str;name:str;role:str;llm:LLMConfigInput
class AgentView(BaseModel):id:str;project_id:str;name:str;role:str;state:str;llm:LLMConfigInput
class AgentPrompt(BaseModel):prompt:str=Field(min_length=1,max_length=20000)
class AgentReply(BaseModel):agent_id:str;text:str
