import sqlite3
from dataclasses import replace

import pytest

from skill_atlas.adapters.storage import migrations
from skill_atlas.adapters.storage.sqlite import SQLiteCatalog
from skill_atlas.errors import CatalogError
from skill_atlas.models import Repository, ScanResult, Skill


def rows(path):
    with sqlite3.connect(path) as connection:
        return connection.execute(
            "SELECT repository_url, skill_path, skill_name, commit_sha FROM skills ORDER BY 1, 2"
        ).fetchall()


def test_rescan_replaces_only_one_repository_and_is_idempotent(tmp_path, scan_result):
    path = tmp_path / "nested" / "catalog.sqlite3"
    catalog = SQLiteCatalog(path)
    catalog.replace_repository(scan_result)
    other = Repository("another", "repo")
    catalog.replace_repository(
        ScanResult(other, "b" * 40, (Skill(other, "SKILL.md", "other", "Other.", "b" * 40),))
    )
    updated = replace(
        scan_result,
        commit_sha="c" * 40,
        skills=(replace(scan_result.skills[0], name="updated", commit_sha="c" * 40),),
    )
    catalog.replace_repository(updated)
    catalog.replace_repository(updated)
    assert len(rows(path)) == 2
    assert rows(path)[0][2:] == ("updated", "c" * 40)
    catalog.replace_repository(replace(updated, skills=()))
    assert rows(path) == [(other.url, "SKILL.md", "other", "b" * 40)]


def test_failed_insert_rolls_back_delete(tmp_path, scan_result):
    path = tmp_path / "catalog.sqlite3"
    catalog = SQLiteCatalog(path)
    catalog.replace_repository(scan_result)
    before = rows(path)
    invalid = replace(scan_result, skills=(scan_result.skills[0], scan_result.skills[0]))
    with pytest.raises(CatalogError):
        catalog.replace_repository(invalid)
    assert rows(path) == before


def test_migration_failure_preserves_schema_version_and_data(tmp_path, scan_result, monkeypatch):
    path = tmp_path / "catalog.sqlite3"
    catalog = SQLiteCatalog(path)
    catalog.replace_repository(scan_result)
    monkeypatch.setattr(
        migrations,
        "MIGRATIONS",
        migrations.MIGRATIONS
        + (migrations.Migration(2, ("ALTER TABLE skills ADD COLUMN extra TEXT", "INVALID SQL")),),
    )
    with pytest.raises(CatalogError):
        catalog.replace_repository(scan_result)
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
        assert "extra" not in [row[1] for row in connection.execute("PRAGMA table_info(skills)")]
        assert connection.execute("SELECT count(*) FROM skills").fetchone()[0] == 2


def test_new_migration_preserves_existing_data(tmp_path, scan_result, monkeypatch):
    path = tmp_path / "catalog.sqlite3"
    SQLiteCatalog(path).replace_repository(scan_result)
    monkeypatch.setattr(
        migrations,
        "MIGRATIONS",
        migrations.MIGRATIONS
        + (
            migrations.Migration(
                2, ("ALTER TABLE skills ADD COLUMN extra TEXT NOT NULL DEFAULT 'default'",)
            ),
        ),
    )
    with sqlite3.connect(path) as connection:
        migrations.migrate(connection)
        migrations.migrate(connection)
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
        assert connection.execute("SELECT extra FROM skills").fetchall() == [
            ("default",),
            ("default",),
        ]


def test_newer_database_is_not_modified(tmp_path, scan_result):
    path = tmp_path / "catalog.sqlite3"
    catalog = SQLiteCatalog(path)
    catalog.replace_repository(scan_result)
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version = 99")
    with pytest.raises(CatalogError, match="newer"):
        catalog.replace_repository(replace(scan_result, skills=()))
    assert len(rows(path)) == 2


def test_catalog_queries_preserve_schema_and_report_failures(tmp_path, scan_result):
    path = tmp_path / "catalog.sqlite3"
    catalog = SQLiteCatalog(path)
    assert catalog.repositories() == ()
    assert catalog.skills(scan_result.repository) == ()
    assert catalog.skill(scan_result.repository, "SKILL.md") is None
    assert not path.exists()
    catalog.replace_repository(scan_result)
    before = path.read_bytes()
    assert catalog.repositories()[0].skill_count == 2
    assert catalog.skills(scan_result.repository) == scan_result.skills
    assert (
        catalog.skill(scan_result.repository, scan_result.skills[0].path) == scan_result.skills[0]
    )
    assert path.read_bytes() == before
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version = 99")
    with pytest.raises(CatalogError, match="newer"):
        catalog.repositories()
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version = 0")
    with pytest.raises(CatalogError, match="Unsupported"):
        catalog.skills(scan_result.repository)
    path.write_bytes(b"corrupt")
    with pytest.raises(CatalogError, match="Could not read"):
        catalog.repositories()
