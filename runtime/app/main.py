from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import router
from app.core.config import settings
from app.persistence.database import Base, engine
import app.persistence.models  # noqa: F401

Base.metadata.create_all(bind=engine)
app=FastAPI(title=settings.app_name,version=settings.version)
app.add_middleware(CORSMiddleware,allow_origins=["http://localhost:5173"],allow_credentials=True,allow_methods=["*"],allow_headers=["*"])
app.include_router(router)
