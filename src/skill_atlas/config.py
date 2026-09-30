import os
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_data_path


@dataclass(frozen=True)
class Settings:
    database_path: Path
    request_timeout: float = 30.0
    git_timeout: float = 120.0
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3.6:latest"
    ollama_timeout: float = 600.0
    ollama_context: int = 32768
    ollama_output_tokens: int = 8192

    @classmethod
    def from_environment(cls) -> "Settings":
        override = os.environ.get("SKILL_ATLAS_DB")
        database_path = (
            Path(override).expanduser()
            if override
            else user_data_path("skill-atlas", appauthor=False, roaming=False) / "catalog.sqlite3"
        )
        return cls(
            database_path=database_path,
            ollama_url=os.environ.get("SKILL_ATLAS_OLLAMA_URL", "http://127.0.0.1:11434"),
            ollama_model=os.environ.get("SKILL_ATLAS_OLLAMA_MODEL", "qwen3.6:latest"),
            ollama_timeout=float(os.environ.get("SKILL_ATLAS_OLLAMA_TIMEOUT", "600")),
            ollama_context=int(os.environ.get("SKILL_ATLAS_OLLAMA_CONTEXT", "32768")),
            ollama_output_tokens=int(os.environ.get("SKILL_ATLAS_OLLAMA_OUTPUT_TOKENS", "8192")),
        )
