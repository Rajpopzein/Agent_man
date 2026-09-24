from fastapi.testclient import TestClient
from app.main import app
client=TestClient(app)
def test_health():assert client.get('/health').status_code==200
def test_project_agent_flow():
 p=client.post('/api/projects',json={'name':'Test','workspace_path':'D:\\AgentMan\\test'});assert p.status_code==201
 a=client.post('/api/agents',json={'project_id':p.json()['id'],'name':'Developer','role':'Developer','llm':{'provider_id':'lmstudio','connection_id':'local','model':'test','endpoint':'http://localhost:1234/v1'}});assert a.status_code==201
 assert client.get('/api/projects/'+p.json()['id']+'/agents').status_code==200
