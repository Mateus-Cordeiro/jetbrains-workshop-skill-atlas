import sqlite3
from pathlib import Path

from skill_atlas.errors import CatalogError
from skill_atlas.models import ScanResult
from skill_atlas.storage.migrations import migrate


class SQLiteCatalog:
    def __init__(self, path: Path) -> None:
        self.path = path

    def replace_repository(self, result: ScanResult) -> None:
        connection = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self.path, timeout=10)
            migrate(connection)
            with connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "DELETE FROM skills WHERE repository_url = ?", (result.repository.url,)
                )
                connection.executemany(
                    """
                    INSERT INTO skills
                    (repository_url, repository_name, skill_path,
                     skill_name, description, commit_sha)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        (
                            result.repository.url,
                            result.repository.full_name,
                            skill.path,
                            skill.name,
                            skill.description,
                            result.commit_sha,
                        )
                        for skill in result.skills
                    ),
                )
        except (OSError, sqlite3.Error) as error:
            raise CatalogError(
                "Could not update the local catalog. "
                "Check its location, permissions, and free space."
            ) from error
        finally:
            if connection is not None:
                connection.close()
