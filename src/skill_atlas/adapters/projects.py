"""Explicit project resolution and independent local Web project registry."""

import os
import sqlite3
import subprocess
from pathlib import Path

from skill_atlas.adapters.git import _git_environment
from skill_atlas.installation import InstallationError


def project_path(value: str | Path | None, *, web: bool = False) -> Path:
    if value is None:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                capture_output=True,
                check=True,
                timeout=10,
                env=_git_environment(None),
            )
            value = os.fsdecode(result.stdout).strip()
        except (OSError, subprocess.SubprocessError) as error:
            raise InstallationError(
                "Outside a Git repository, provide --project explicitly."
            ) from error
    path = Path(value).expanduser()
    if web and not path.is_absolute():
        raise InstallationError("Register an absolute local project path.")
    try:
        path = path.resolve(strict=True)
        if not path.is_dir():
            raise InstallationError("The project path must be an existing directory.")
        return path
    except (OSError, RuntimeError) as error:
        raise InstallationError(
            "The project path must be an existing accessible directory."
        ) from error


class LocalProjectRegistry:
    def __init__(self, path: Path) -> None:
        self.path = path

    def list(self) -> tuple[Path, ...]:
        if not self.path.exists():
            return ()
        try:
            with sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True) as connection:
                return tuple(
                    Path(row[0])
                    for row in connection.execute("SELECT path FROM projects ORDER BY path")
                )
        except sqlite3.Error as error:
            raise InstallationError("Could not read the local project registry.") from error

    def register(self, project: Path) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(self.path) as connection:
                connection.execute("CREATE TABLE IF NOT EXISTS projects (path TEXT PRIMARY KEY)")
                connection.execute("INSERT OR IGNORE INTO projects VALUES (?)", (str(project),))
        except (OSError, sqlite3.Error) as error:
            raise InstallationError("Could not save the local project registry.") from error
