from collections.abc import Generator
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from app.core.config import settings

class Base(DeclarativeBase):
    pass

def _database_url() -> str:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    path: Path = settings.data_dir / "agent-man.db"
    return f"sqlite:///{path.as_posix()}"

engine = create_engine(_database_url(), connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

def get_session() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session
