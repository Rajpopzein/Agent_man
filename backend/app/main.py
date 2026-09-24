from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app=FastAPI(title="Agent Man Runtime",version="0.1.0")
app.add_middleware(CORSMiddleware,allow_origins=["http://localhost:5173"],allow_credentials=True,allow_methods=["*"],allow_headers=["*"])

class Health(BaseModel):
    status:str
    runtime:str
    version:str

@app.get("/health",response_model=Health)
def health()->Health:
    return Health(status="healthy",runtime="agent-man",version="0.1.0")

@app.get("/api/dashboard")
def dashboard():
    return {"project":{"name":"Agent Man Dev","sandbox":"healthy"},"agents":[],"tasks":[],"ports":[],"events":[]}
