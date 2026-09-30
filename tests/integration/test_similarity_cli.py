import json
import re
import sqlite3
from dataclasses import replace
from html import unescape

import pytest
from fastapi.testclient import TestClient
from rich.text import Text
from typer.testing import CliRunner

from skill_atlas import runtime
from skill_atlas.adapters.storage.sqlite import SQLiteCatalog
from skill_atlas.cli.app import create_app
from skill_atlas.config import Settings
from skill_atlas.models import ScanResult

runner = CliRunner()


def invoke(source, *options):
    return runner.invoke(
        create_app(),
        ["similar", source.repository.url, source.path, *options],
        terminal_width=240,
        env={"COLUMNS": "240"},
    )


def test_help_documents_source_and_json():
    result = runner.invoke(create_app(), ["--help"])
    assert result.exit_code == 0 and "similar" in result.stdout
    result = runner.invoke(create_app(), ["similar", "--help"])
    assert result.exit_code == 0
    help_text = Text.from_ansi(result.stdout).plain.casefold()
    for argument in ("repository_url", "skill_path", "--json"):
        assert argument in help_text


def test_cli_and_web_share_ranking_grouping_and_locations(web_environment, similar_catalog):
    source = similar_catalog.source
    before = web_environment.settings.database_path.read_bytes()
    command = invoke(source, "--json")
    assert command.exit_code == 0, command.output
    data = json.loads(command.stdout)
    assert command.stderr == ""
    assert data["source"]["skill_path"] == source.path
    assert [match["score"] for match in data["matches"]] == pytest.approx([100, 80])
    assert [len(match["locations"]) for match in data["matches"]] == [3, 1]
    assert [location["skill_path"] for location in data["matches"][0]["locations"]] == [
        ".agents/skills/review/SKILL.md",
        "nested/copy/SKILL.md",
        "review #?/SKILL.md",
    ]
    with TestClient(web_environment.app, base_url="http://127.0.0.1") as client:
        response = client.get(
            "/similar", params={"repository_url": source.repository.url, "skill_path": source.path}
        )
    assert response.status_code == 200
    assert [
        int(score) for score in re.findall(r'aria-valuetext="(\d+)% similarity"', response.text)
    ] == [match["display_score"] for match in data["matches"]]
    web_locations = re.findall(
        r'data-skill-path="([^"]*)" data-skill-repository="([^"]*)"', response.text
    )
    assert [(unescape(path), unescape(repository)) for path, repository in web_locations] == [
        (location["skill_path"], location["repository_url"])
        for match in data["matches"]
        for location in match["locations"]
    ]
    text = invoke(source)
    assert text.exit_code == 0 and text.stderr == ""
    for expected in (
        "2 result groups",
        "1. code-review · 100%",
        "2. patch-audit · 80%",
        "Same metadata · 3 locations",
        similar_catalog.remote.url,
    ):
        assert expected in text.stdout
    assert source.description in text.stdout and "\x1b" not in text.stdout
    assert web_environment.settings.database_path.read_bytes() == before
    assert not web_environment.requests


def test_search_is_offline_uses_exact_identity_and_current_catalog(
    tmp_path, monkeypatch, scan_result
):
    database = tmp_path / "chosen" / "catalog.sqlite3"
    monkeypatch.setenv("SKILL_ATLAS_DB", str(database))
    catalog = SQLiteCatalog(database)
    source = replace(scan_result.skills[0], path=" root #?/SKILL.md ")
    same_name = replace(source, path="other/SKILL.md", description="Bake sourdough bread.")
    catalog.replace_repository(replace(scan_result, skills=(source, same_name)))
    before = database.read_bytes()

    def forbidden(*args, **kwargs):
        pytest.fail(
            "A local similarity search must not scan, contact GitHub, or resolve credentials"
        )

    monkeypatch.setattr(runtime, "github_token", forbidden)
    monkeypatch.setattr(runtime, "create_scanner", forbidden)
    monkeypatch.setattr(runtime.httpx, "Client", forbidden)
    command = runner.invoke(
        create_app(), ["similar", "https://github.com/ACME/skills.git/", source.path, "--json"]
    )
    assert command.exit_code == 0, command.output
    match = json.loads(command.stdout)["matches"][0]
    assert match["score"] == pytest.approx(20)
    assert match["locations"][0]["skill_path"] == same_name.path
    assert database.read_bytes() == before

    updated = replace(source, commit_sha="b" * 40)
    catalog.replace_repository(ScanResult(source.repository, updated.commit_sha, (updated,)))
    command = invoke(source, "--json")
    assert command.exit_code == 0
    assert json.loads(command.stdout)["source"]["commit_sha"] == updated.commit_sha
    assert json.loads(command.stdout)["matches"] == []
    text = invoke(source)
    assert text.exit_code == 0 and "No similar skills found" in text.stdout
    catalog.replace_repository(ScanResult(source.repository, "c" * 40, ()))
    missing = invoke(source, "--json")
    assert missing.exit_code == 1 and missing.stdout == ""
    assert "starting skill is not in the catalog" in missing.stderr
    assert "skill-atlas scan" in missing.stderr


@pytest.mark.parametrize("options", [[], ["--json"]])
@pytest.mark.parametrize("state", ["missing", "empty", "corrupt", "older", "newer", "directory"])
def test_missing_source_and_catalog_failures_preserve_database(scan_result, state, options):
    database = Settings.from_environment().database_path
    if state in ("empty", "older", "newer"):
        SQLiteCatalog(database).replace_repository(replace(scan_result, skills=()))
        if state != "empty":
            with sqlite3.connect(database) as connection:
                connection.execute(f"PRAGMA user_version = {0 if state == 'older' else 99}")
    elif state == "corrupt":
        database.write_bytes(b"not a database")
    elif state == "directory":
        database.mkdir()
    before = database.read_bytes() if database.is_file() else None
    command = invoke(scan_result.skills[0], *options)
    assert command.exit_code == 1 and command.stdout == ""
    assert "Error:" in command.stderr and "Traceback" not in command.stderr
    assert "No similar skills found" not in command.stderr
    if before is not None:
        assert database.read_bytes() == before
    else:
        assert database.is_dir() if state == "directory" else not database.exists()


@pytest.mark.parametrize(
    "arguments",
    [
        [],
        ["https://github.com/acme/skills"],
        ["https://token:secret@github.com/acme/skills", "SKILL.md"],
        ["https://github.com/acme/skills", ""],
    ],
)
def test_invalid_usage_never_reads_catalog(arguments, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Invalid arguments must not open the catalog")

    monkeypatch.setattr(runtime, "create_similarity", forbidden)
    command = runner.invoke(create_app(), ["similar", *arguments, "--json"])
    assert command.exit_code == 2 and command.stdout == ""
    assert "secret" not in command.stderr


def test_scan_created_catalog_can_be_searched_without_rescanning(scan_harness):
    repository = scan_harness.add_repository()
    for path in ("SKILL.md", ".agents/skills/copy/SKILL.md"):
        repository.write(path, "---\nname: review\ndescription: Review code changes.\n---\n")
    snapshot = repository.commit()
    assert scan_harness.scan(repository).exit_code == 0
    source = SQLiteCatalog(scan_harness.database).skill(repository.identity, "SKILL.md")
    before = scan_harness.database.read_bytes()
    result = invoke(source, "--json")
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["source"]["commit_sha"] == snapshot.commit_sha
    assert data["matches"][0]["display_score"] == 100
    assert data["matches"][0]["locations"][0]["skill_path"] == ".agents/skills/copy/SKILL.md"
    assert scan_harness.database.read_bytes() == before
