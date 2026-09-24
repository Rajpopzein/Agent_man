import json
from urllib.request import Request,urlopen
from app.providers.base import Provider
class OpenAICompatibleProvider(Provider):
 def chat(self,model,messages,endpoint=None):
  if not endpoint:raise ValueError('Provider endpoint is required')
  req=Request(endpoint.rstrip('/')+'/chat/completions',data=json.dumps({'model':model,'messages':messages,'temperature':0.2}).encode(),headers={'Content-Type':'application/json'},method='POST')
  with urlopen(req,timeout=120) as r:data=json.loads(r.read().decode())
  return data['choices'][0]['message']['content']
