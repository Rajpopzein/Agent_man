from fastapi import APIRouter
from app.core.config import settings

router=APIRouter()

@router.get("/health")
def health():
    return {"status":"healthy","runtime":"agent-man","version":settings.version}

@router.get("/api/dashboard")
def dashboard():
    return {"project":None,"agents":[],"tasks":[],"ports":[],"events":[]}
