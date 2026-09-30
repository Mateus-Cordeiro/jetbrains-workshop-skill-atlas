import os
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_data_path


@dataclass(frozen=True)
class Settings:
    database_path: Path
    request_timeout: float = 30.0
    git_timeout: float = 120.0

    @classmethod
    def from_environment(cls) -> "Settings":
        override = os.environ.get("SKILL_ATLAS_DB")
        database_path = (
            Path(override).expanduser()
            if override
            else user_data_path("skill-atlas", appauthor=False, roaming=False) / "catalog.sqlite3"
        )
        return cls(database_path=database_path)
