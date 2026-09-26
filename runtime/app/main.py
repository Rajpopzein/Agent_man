from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import app.persistence.models  # noqa: F401
from app.api.ai_connections import router as ai_router
from app.api.multi_agent import router as multi_agent_router
from app.api.orchestration import router as orchestration_router
from app.api.tools import router as tools_router
from app.api.routes import router
from app.core.config import settings
from app.persistence.database import SessionLocal
from app.persistence.migrations import run_migrations
from app.tools.service import sync_builtin_tools

run_migrations()
with SessionLocal() as db:
    sync_builtin_tools(db)

app = FastAPI(title=settings.app_name, version=settings.version)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)
app.include_router(ai_router)
app.include_router(multi_agent_router)
app.include_router(orchestration_router)
app.include_router(tools_router)
