import sqlite3
from pathlib import Path

from skill_atlas.adapters.storage.migrations import MIGRATIONS, migrate
from skill_atlas.errors import CatalogError
from skill_atlas.models import Repository, RepositorySummary, ScanResult, Skill


class SQLiteCatalog:
    def __init__(self, path: Path) -> None:
        self.path = path

    def _query(self, sql: str, parameters: tuple[str, ...] = ()) -> list[sqlite3.Row]:
        connection = None
        try:
            if not self.path.exists():
                return []
            connection = sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True)
            connection.row_factory = sqlite3.Row
            connection.execute("BEGIN")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version > MIGRATIONS[-1].version:
                raise CatalogError("This catalog requires a newer skill-atlas version.")
            if version != MIGRATIONS[-1].version:
                raise CatalogError("Unsupported catalog schema. Run a scan to initialize it.")
            return list(connection.execute(sql, parameters))
        except (OSError, sqlite3.Error) as error:
            raise CatalogError(
                "Could not read the local catalog. Check its location and permissions."
            ) from error
        finally:
            if connection is not None:
                connection.close()

    @staticmethod
    def _skill(row: sqlite3.Row) -> Skill:
        return Skill(
            Repository(*row["repository_name"].split("/")),
            row["skill_path"],
            row["skill_name"],
            row["description"],
            row["commit_sha"],
        )

    def repositories(self) -> tuple[RepositorySummary, ...]:
        return tuple(
            RepositorySummary(
                Repository(*row["repository_name"].split("/")),
                row["skill_count"],
                row["commit_sha"],
            )
            for row in self._query(
                "SELECT repository_url, repository_name, commit_sha, count(*) AS skill_count "
                "FROM skills GROUP BY repository_url ORDER BY repository_url"
            )
        )

    def skills(self, repository: Repository | None = None) -> tuple[Skill, ...]:
        return tuple(
            self._skill(row)
            for row in self._query(
                "SELECT * FROM skills "
                + ("WHERE repository_url = ? " if repository else "")
                + "ORDER BY repository_url, skill_name, skill_path",
                (repository.url,) if repository else (),
            )
        )

    def skill(self, repository: Repository, path: str) -> Skill | None:
        rows = self._query(
            "SELECT * FROM skills WHERE repository_url = ? AND skill_path = ?",
            (repository.url, path),
        )
        return self._skill(rows[0]) if rows else None

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
