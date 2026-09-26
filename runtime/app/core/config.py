from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class Settings:
    app_name: str = "Agent Man Runtime"
    version: str = "0.1.0"
    api_revision: str = "executive-tools-v2"
    data_dir: Path = Path.home() / ".agent-man"

settings = Settings()
