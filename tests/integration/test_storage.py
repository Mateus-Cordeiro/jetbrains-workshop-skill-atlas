import sqlite3
from dataclasses import replace

import pytest

from skill_atlas.adapters.storage import migrations
from skill_atlas.adapters.storage.sqlite import SQLiteCatalog
from skill_atlas.errors import CatalogError
from skill_atlas.models import Repository, ScanResult, Skill

CURRENT = migrations.MIGRATIONS[-1].version


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
        + (
            migrations.Migration(
                CURRENT + 1, ("ALTER TABLE skills ADD COLUMN extra TEXT", "INVALID SQL")
            ),
        ),
    )
    with pytest.raises(CatalogError):
        catalog.replace_repository(scan_result)
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == CURRENT
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
                CURRENT + 1,
                ("ALTER TABLE skills ADD COLUMN extra TEXT NOT NULL DEFAULT 'default'",),
            ),
        ),
    )
    with sqlite3.connect(path) as connection:
        migrations.migrate(connection)
        migrations.migrate(connection)
        assert connection.execute("PRAGMA user_version").fetchone()[0] == CURRENT + 1
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


def test_whole_catalog_read_is_ordered_read_only_and_keeps_duplicate_names(tmp_path, scan_result):
    from dataclasses import replace

    from skill_atlas.models import Repository

    catalog = SQLiteCatalog(tmp_path / "catalog.sqlite3")
    assert catalog.skills() == ()
    assert not catalog.path.exists()
    second = Repository("zebra", "repo")
    catalog.replace_repository(replace(scan_result, repository=second))
    duplicate = replace(scan_result.skills[0], path="a copy/SKILL.md")
    catalog.replace_repository(replace(scan_result, skills=(*scan_result.skills, duplicate)))
    before = catalog.path.read_bytes()
    skills = catalog.skills()
    assert [(skill.repository.url, skill.path) for skill in skills] == [
        (scan_result.repository.url, "a copy/SKILL.md"),
        (scan_result.repository.url, "review/SKILL.md"),
        (scan_result.repository.url, "release notes/SKILL.md"),
        (second.url, "review/SKILL.md"),
        (second.url, "release notes/SKILL.md"),
    ]
    assert catalog.path.read_bytes() == before


def stars(path):
    with sqlite3.connect(path) as connection:
        return connection.execute("SELECT * FROM starred_skills ORDER BY 1, 2").fetchall()


def create_v1_catalog(path, scan_result):
    """A catalog written by a release before stars, using its shipped migration."""
    with sqlite3.connect(path) as connection:
        for statement in migrations.MIGRATIONS[0].statements:
            connection.execute(statement)
        connection.execute("PRAGMA user_version = 1")
        connection.executemany(
            "INSERT INTO skills VALUES (?, ?, ?, ?, ?, ?)",
            [
                (
                    skill.repository.url,
                    skill.repository.full_name,
                    skill.path,
                    skill.name,
                    skill.description,
                    skill.commit_sha,
                )
                for skill in scan_result.skills
            ],
        )
    connection.close()


def test_existing_catalog_is_readable_then_upgrades_in_place(tmp_path, scan_result):
    path = tmp_path / "catalog.sqlite3"
    create_v1_catalog(path, scan_result)
    catalog = SQLiteCatalog(path)
    before = path.read_bytes()
    assert catalog.skills() == tuple(
        sorted(scan_result.skills, key=lambda skill: (skill.name, skill.path))
    )
    assert catalog.skill(scan_result.repository, scan_result.skills[0].path).starred is False
    assert catalog.repositories()[0].skill_count == 2
    assert path.read_bytes() == before  # Reads never migrate.
    review = scan_result.skills[0]
    assert catalog.set_starred(review.repository, review.path, True) == replace(
        review, starred=True
    )
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == CURRENT
    assert rows(path) == [
        (scan_result.repository.url, "release notes/SKILL.md", "release-notes", "a" * 40),
        (scan_result.repository.url, "review/SKILL.md", "code-review", "a" * 40),
    ]
    assert [skill.starred for skill in catalog.skills()] == [True, False]


def test_failed_star_migration_rolls_back_and_keeps_catalog_readable(
    tmp_path, scan_result, monkeypatch
):
    path = tmp_path / "catalog.sqlite3"
    create_v1_catalog(path, scan_result)
    failing = migrations.Migration(
        migrations.MIGRATIONS[1].version, (*migrations.MIGRATIONS[1].statements, "INVALID SQL")
    )
    monkeypatch.setattr(migrations, "MIGRATIONS", (migrations.MIGRATIONS[0], failing))
    review = scan_result.skills[0]
    with pytest.raises(CatalogError):
        SQLiteCatalog(path).set_starred(review.repository, review.path, True)
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master")}
    connection.close()
    assert "starred_skills" not in tables
    assert len(SQLiteCatalog(path).skills()) == 2


def test_rescans_keep_surviving_stars_and_drop_removed_identities(tmp_path, scan_result):
    path = tmp_path / "catalog.sqlite3"
    catalog = SQLiteCatalog(path)
    review, notes = scan_result.skills
    copy = replace(review, path=".agents/skills/review/SKILL.md")
    catalog.replace_repository(replace(scan_result, skills=(review, notes, copy)))
    other = Repository("another", "repo")
    other_skill = Skill(other, "SKILL.md", "other", "Other.", "b" * 40)
    catalog.replace_repository(ScanResult(other, "b" * 40, (other_skill,)))
    for skill in (review, notes, other_skill):
        catalog.set_starred(skill.repository, skill.path, True)
    assert not catalog.skill(copy.repository, copy.path).starred  # Copies star independently.

    moved = replace(notes, path="moved/SKILL.md")
    stored = catalog.replace_repository(
        replace(scan_result, commit_sha="c" * 40, skills=(replace(review, name="updated"), moved))
    )
    assert [(skill.path, skill.starred) for skill in stored.skills] == [
        ("review/SKILL.md", True),
        ("moved/SKILL.md", False),
    ]
    assert stars(path) == [(review.repository.url, review.path), (other.url, "SKILL.md")]

    before = stars(path)
    with pytest.raises(CatalogError):
        catalog.replace_repository(replace(scan_result, skills=(review, review)))
    assert stars(path) == before
    catalog.replace_repository(replace(scan_result, skills=()))
    assert stars(path) == [(other.url, "SKILL.md")]
    # A rescan restoring a removed path starts unstarred.
    restored = catalog.replace_repository(scan_result)
    assert not any(skill.starred for skill in restored.skills)


def test_star_writes_are_idempotent_and_never_create_or_downgrade_catalogs(tmp_path, scan_result):
    path = tmp_path / "catalog.sqlite3"
    catalog = SQLiteCatalog(path)
    review = scan_result.skills[0]
    assert catalog.set_starred(review.repository, review.path, True) is None
    assert not path.exists()
    catalog.replace_repository(scan_result)
    assert catalog.set_starred(review.repository, "missing/SKILL.md", True) is None
    assert catalog.set_starred(Repository("ACME", "Skills"), review.path, True).starred
    assert catalog.set_starred(review.repository, review.path, True).starred
    assert stars(path) == [(review.repository.url, review.path)]
    for _ in range(2):
        assert catalog.set_starred(review.repository, review.path, False) == review
    assert stars(path) == []
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version = 99")
    connection.close()
    before = path.read_bytes()
    with pytest.raises(CatalogError, match="newer"):
        catalog.set_starred(review.repository, review.path, True)
    assert path.read_bytes() == before
