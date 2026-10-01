import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

from skill_atlas.adapters.storage.migrations import MIGRATIONS, migrate
from skill_atlas.errors import CatalogError
from skill_atlas.models import Repository, RepositorySummary, ScanResult, Skill

# Catalogs created before stars remain readable, without stars, until a write migrates them.
_STARS_VERSION = 3
_SKILLS = (
    "SELECT skills.*, starred_skills.skill_path IS NOT NULL AS starred FROM skills "
    "LEFT JOIN starred_skills ON starred_skills.repository_url = skills.repository_url "
    "AND starred_skills.skill_path = skills.skill_path "
)


class SQLiteCatalog:
    def __init__(self, path: Path) -> None:
        self.path = path

    @contextmanager
    def read_connection(self) -> Iterator[sqlite3.Connection | None]:
        connection = None
        try:
            if not self.path.exists():
                yield None
                return
            connection = sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True)
            connection.row_factory = sqlite3.Row
            connection.execute("BEGIN")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version > MIGRATIONS[-1].version:
                raise CatalogError("This catalog requires a newer skill-atlas version.")
            if version < 1:
                raise CatalogError("Unsupported catalog schema. Run a scan to initialize it.")
            if version < _STARS_VERSION:
                # A connection-local table; the catalog file itself is never modified by reads.
                connection.execute(
                    "CREATE TEMP TABLE starred_skills (repository_url TEXT, skill_path TEXT)"
                )
            yield connection
        except (OSError, sqlite3.Error) as error:
            raise CatalogError(
                "Could not read the local catalog. Check its location and permissions."
            ) from error
        finally:
            if connection is not None:
                connection.close()

    def _query(self, sql: str, parameters: tuple[str, ...] = ()) -> list[sqlite3.Row]:
        with self.read_connection() as connection:
            return list(connection.execute(sql, parameters)) if connection is not None else []

    @staticmethod
    def _skill(row: sqlite3.Row) -> Skill:
        return Skill(
            Repository(*row["repository_name"].split("/")),
            row["skill_path"],
            row["skill_name"],
            row["description"],
            row["commit_sha"],
            bool(row["starred"]),
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
                _SKILLS
                + ("WHERE skills.repository_url = ? " if repository else "")
                + "ORDER BY skills.repository_url, skill_name, skills.skill_path",
                (repository.url,) if repository else (),
            )
        )

    def skill(self, repository: Repository, path: str) -> Skill | None:
        rows = self._query(
            _SKILLS + "WHERE skills.repository_url = ? AND skills.skill_path = ?",
            (repository.url, path),
        )
        return self._skill(rows[0]) if rows else None

    @contextmanager
    def _transaction(self, message: str) -> Iterator[sqlite3.Connection]:
        """Migrate under the write lock, then run one separate atomic write transaction."""
        connection = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self.path, timeout=10)
            migrate(connection)
            connection.row_factory = sqlite3.Row
            with connection:
                connection.execute("BEGIN IMMEDIATE")
                yield connection
        except (OSError, sqlite3.Error) as error:
            raise CatalogError(message) from error
        finally:
            if connection is not None:
                connection.close()

    def replace_repository(self, result: ScanResult) -> ScanResult:
        with self._transaction(
            "Could not update the local catalog. Check its location, permissions, and free space."
        ) as connection:
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
            # Stars follow catalog identity: surviving paths keep them, removed paths lose them.
            connection.execute(
                "DELETE FROM starred_skills WHERE repository_url = ? AND skill_path NOT IN "
                "(SELECT skill_path FROM skills WHERE repository_url = ?)",
                (result.repository.url, result.repository.url),
            )
            starred = {
                row["skill_path"]
                for row in connection.execute(
                    "SELECT skill_path FROM starred_skills WHERE repository_url = ?",
                    (result.repository.url,),
                )
            }
        return replace(
            result,
            skills=tuple(replace(skill, starred=skill.path in starred) for skill in result.skills),
        )

    def set_starred(self, repository: Repository, path: str, starred: bool) -> Skill | None:
        if not self.path.exists():
            # A missing catalog has no skills to star; do not create one.
            return None
        with self._transaction(
            "Could not update the local catalog. Check its location and permissions."
        ) as connection:
            row = connection.execute(
                "SELECT *, 0 AS starred FROM skills WHERE repository_url = ? AND skill_path = ?",
                (repository.url, path),
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                "INSERT OR IGNORE INTO starred_skills VALUES (?, ?)"
                if starred
                else "DELETE FROM starred_skills WHERE repository_url = ? AND skill_path = ?",
                (repository.url, path),
            )
        return replace(self._skill(row), starred=starred)
