from fastapi import APIRouter,Depends,HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.agents.runner import run_agent
from app.api.schemas import *
from app.core.config import settings
from app.persistence.database import get_session
from app.persistence.models import AgentRecord,ProjectRecord
router=APIRouter()
@router.get('/health')
def health():return {'status':'healthy','runtime':'agent-man','version':settings.version}
@router.post('/api/projects',response_model=ProjectView,status_code=201)
def create_project(body:ProjectCreate,db:Session=Depends(get_session)):
 r=ProjectRecord(name=body.name,workspace_path=body.workspace_path);db.add(r);db.commit();db.refresh(r);return r
@router.get('/api/projects',response_model=list[ProjectView])
def projects(db:Session=Depends(get_session)):return db.scalars(select(ProjectRecord).order_by(ProjectRecord.created_at.desc())).all()
@router.post('/api/agents',response_model=AgentView,status_code=201)
def create_agent(body:AgentCreate,db:Session=Depends(get_session)):
 if not db.get(ProjectRecord,body.project_id):raise HTTPException(404,'Project not found')
 l=body.llm;r=AgentRecord(project_id=body.project_id,name=body.name,role=body.role,provider_id=l.provider_id,connection_id=l.connection_id,model=l.model,context_limit=l.context_limit,temperature_milli=round(l.temperature*1000),cloud_fallback_allowed=l.cloud_fallback_allowed);db.add(r);db.commit();db.refresh(r);return view(r,l.endpoint)
@router.get('/api/projects/{pid}/agents',response_model=list[AgentView])
def agents(pid:str,db:Session=Depends(get_session)):return [view(x) for x in db.scalars(select(AgentRecord).where(AgentRecord.project_id==pid)).all()]
@router.post('/api/agents/{aid}/chat',response_model=AgentReply)
def chat(aid:str,body:AgentPrompt,endpoint:str='http://localhost:1234/v1',db:Session=Depends(get_session)):
 a=db.get(AgentRecord,aid)
 if not a:raise HTTPException(404,'Agent not found')
 try:return AgentReply(agent_id=a.id,text=run_agent(a,body.prompt,endpoint))
 except Exception as e:raise HTTPException(502,'Provider error: '+str(e))
def view(r,endpoint=None):return AgentView(id=r.id,project_id=r.project_id,name=r.name,role=r.role,state=r.state,llm=LLMConfigInput(provider_id=r.provider_id,connection_id=r.connection_id,model=r.model,endpoint=endpoint,context_limit=r.context_limit,temperature=r.temperature_milli/1000,cloud_fallback_allowed=r.cloud_fallback_allowed))
