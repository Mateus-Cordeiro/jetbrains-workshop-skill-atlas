"""Append migrations here; never edit a migration after it has shipped."""

import sqlite3
from dataclasses import dataclass

from skill_atlas.errors import CatalogError


@dataclass(frozen=True)
class Migration:
    version: int
    statements: tuple[str, ...]


MIGRATIONS = (
    Migration(
        version=1,
        statements=(
            """
            CREATE TABLE skills (
                repository_url TEXT NOT NULL,
                repository_name TEXT NOT NULL,
                skill_path TEXT NOT NULL,
                skill_name TEXT NOT NULL,
                description TEXT NOT NULL,
                commit_sha TEXT NOT NULL,
                PRIMARY KEY (repository_url, skill_path)
            )
            """,
        ),
    ),
)


def migrate(connection: sqlite3.Connection) -> None:
    # Take the write lock before reading the version, including on first use.
    # Each statement and the version marker roll back together on failure.
    with connection:
        connection.execute("BEGIN IMMEDIATE")
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version > MIGRATIONS[-1].version:
            raise CatalogError(
                "This catalog was created by a newer skill-atlas version. Upgrade first."
            )
        for migration in MIGRATIONS:
            if migration.version > version:
                for statement in migration.statements:
                    connection.execute(statement)
                connection.execute(f"PRAGMA user_version = {migration.version}")
