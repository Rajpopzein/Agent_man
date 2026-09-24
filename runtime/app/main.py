from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import app.persistence.models  # noqa: F401
from app.api.routes import router
from app.core.config import settings
from app.persistence.migrations import run_migrations

run_migrations()

app = FastAPI(title=settings.app_name, version=settings.version)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)
