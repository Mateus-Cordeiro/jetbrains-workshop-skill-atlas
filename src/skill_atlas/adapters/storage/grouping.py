"""Derived groupings share SQLite and read transactions with catalog metadata."""

import json
import sqlite3
from dataclasses import asdict

from skill_atlas.adapters.storage.migrations import migrate
from skill_atlas.adapters.storage.sqlite import SQLiteCatalog
from skill_atlas.errors import CatalogError
from skill_atlas.grouping import Grouping, GroupingCatalog, Perspective, SkillGroup, SkillIdentity


class SQLiteGroups:
    def __init__(self, catalog: SQLiteCatalog) -> None:
        self.catalog = catalog

    def read(self, perspective: Perspective) -> GroupingCatalog:
        with self.catalog.read_connection() as connection:
            if connection is None:
                return GroupingCatalog((), None)
            skills = tuple(
                self.catalog._skill(row)
                for row in connection.execute(
                    "SELECT * FROM skills ORDER BY repository_url, skill_name, skill_path"
                )
            )
            # Existing catalogs remain readable without a migration or a rescan.
            if connection.execute("PRAGMA user_version").fetchone()[0] == 1:
                return GroupingCatalog(skills, None)
            row = connection.execute(
                "SELECT * FROM skill_groupings WHERE perspective = ?", (perspective.value,)
            ).fetchone()
            if row is None:
                return GroupingCatalog(skills, None)
            try:
                raw = json.loads(row["groups_json"])
                groups = tuple(
                    SkillGroup(
                        group["title"],
                        tuple(SkillIdentity(**member) for member in group["members"]),
                    )
                    for group in raw
                )
                if not groups or any(
                    not isinstance(g.title, str)
                    or not g.title.strip()
                    or not g.members
                    or any(
                        not isinstance(m.repository_url, str) or not isinstance(m.path, str)
                        for m in g.members
                    )
                    for g in groups
                ):
                    raise ValueError("Invalid stored groups")
            except (ValueError, TypeError, KeyError) as error:
                raise CatalogError(
                    "Could not read saved groups. The grouping data is invalid."
                ) from error
            return GroupingCatalog(
                skills, Grouping(perspective, row["fingerprint"], row["model"], groups)
            )

    def save(self, grouping: Grouping) -> None:
        connection = None
        try:
            self.catalog.path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self.catalog.path, timeout=10)
            migrate(connection)
            with connection:
                connection.execute(
                    "INSERT INTO skill_groupings VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(perspective) DO UPDATE SET fingerprint=excluded.fingerprint, "
                    "model=excluded.model, groups_json=excluded.groups_json",
                    (
                        grouping.perspective.value,
                        grouping.fingerprint,
                        grouping.model,
                        json.dumps([asdict(group) for group in grouping.groups]),
                    ),
                )
        except (OSError, sqlite3.Error) as error:
            raise CatalogError(
                "Could not save groups. Previous groups are unchanged. "
                "Check catalog permissions and free space."
            ) from error
        finally:
            if connection is not None:
                connection.close()
