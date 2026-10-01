import json
import sqlite3
import subprocess
from dataclasses import replace

import pytest
from rich.text import Text
from typer.testing import CliRunner

from skill_atlas import runtime
from skill_atlas.adapters.storage.sqlite import SQLiteCatalog
from skill_atlas.cli.app import create_app
from skill_atlas.config import Settings
from skill_atlas.models import Repository, ScanResult

runner = CliRunner()


def invoke(*arguments):
    return runner.invoke(create_app(), list(arguments), terminal_width=240, env={"COLUMNS": "240"})


@pytest.fixture
def catalog(scan_result):
    catalog = SQLiteCatalog(Settings.from_environment().database_path)
    review = scan_result.skills[0]
    catalog.replace_repository(
        replace(
            scan_result,
            skills=(*scan_result.skills, replace(review, path=".agents/skills/review/SKILL.md")),
        )
    )
    remote = replace(review, repository=Repository("zebra", "skills"), path="review #?/SKILL.md")
    catalog.replace_repository(ScanResult(remote.repository, remote.commit_sha, (remote,)))
    return catalog


def starred(catalog):
    return [(skill.repository.url, skill.path) for skill in catalog.skills() if skill.starred]


def test_star_and_unstar_are_idempotent_offline_and_persisted(catalog, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("Starring must not resolve credentials, use subprocesses, or create a client")

    monkeypatch.setattr(runtime, "github_token", unexpected)
    monkeypatch.setattr(runtime.httpx, "Client", unexpected)
    monkeypatch.setattr(subprocess, "Popen", unexpected)
    # Accepted URL forms normalize to the stored identity.
    url = "https://github.com:443/ACME/skills.git/"
    for _ in range(2):
        result = invoke("star", url, "review/SKILL.md")
        assert result.exit_code == 0, result.output
        assert result.stdout == "Starred code-review · Acme/skills · review/SKILL.md\n"
        assert result.stderr == ""
    assert starred(catalog) == [("https://github.com/acme/skills", "review/SKILL.md")]
    # Identical copies at different paths are separate identities.
    assert invoke("star", url, ".agents/skills/review/SKILL.md").exit_code == 0
    for _ in range(2):
        result = invoke("unstar", url, "review/SKILL.md")
        assert result.exit_code == 0, result.output
        assert result.stdout.startswith("Unstarred code-review · ")
    assert starred(catalog) == [
        ("https://github.com/acme/skills", ".agents/skills/review/SKILL.md")
    ]


@pytest.mark.parametrize("command", ["star", "unstar"])
@pytest.mark.parametrize("state", ["missing-catalog", "unknown-path", "unknown-repository"])
def test_unknown_identities_exit_one_without_creating_or_changing_catalogs(
    command, state, scan_result
):
    catalog = SQLiteCatalog(Settings.from_environment().database_path)
    repository, path = "https://github.com/acme/skills", "review/SKILL.md"
    if state != "missing-catalog":
        catalog.replace_repository(scan_result)
        catalog.set_starred(scan_result.repository, path, True)
    if state == "unknown-path":
        path = "Review/SKILL.md"
    elif state == "unknown-repository":
        repository = "https://github.com/acme/other"
    before = catalog.path.read_bytes() if catalog.path.exists() else None
    result = invoke(command, repository, path)
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "Skill not found in the catalog" in result.stderr
    assert (catalog.path.read_bytes() if catalog.path.exists() else None) == before


@pytest.mark.parametrize(
    "arguments",
    [
        ["https://token:secret@github.com/acme/skills", "review/SKILL.md"],
        ["https://github.com/acme/skills/tree/main", "review/SKILL.md"],
        ["https://github.com/acme/skills", ""],
        ["https://github.com/acme/skills"],
    ],
)
@pytest.mark.parametrize("command", ["star", "unstar"])
def test_invalid_usage_exits_two(command, arguments):
    result = invoke(command, *arguments)
    assert result.exit_code == 2
    assert result.stdout == "" and "secret" not in result.stderr
    assert not Settings.from_environment().database_path.exists()


@pytest.mark.parametrize("state", ["corrupt", "newer"])
def test_catalog_errors_exit_one_without_modification(catalog, state):
    if state == "corrupt":
        catalog.path.write_bytes(b"not a database")
    else:
        with sqlite3.connect(catalog.path) as connection:
            connection.execute("PRAGMA user_version = 99")
        connection.close()
    before = catalog.path.read_bytes()
    result = invoke("star", "https://github.com/acme/skills", "review/SKILL.md")
    assert result.exit_code == 1 and result.stdout == ""
    assert "Error:" in result.stderr and "not found" not in result.stderr
    assert catalog.path.read_bytes() == before


def test_filter_starred_marks_restricts_and_keeps_matching_rules(catalog):
    catalog.set_starred(Repository("acme", "skills"), "review/SKILL.md", True)
    catalog.set_starred(Repository("zebra", "skills"), "review #?/SKILL.md", True)
    before = catalog.path.read_bytes()
    listing = invoke("filter", "--no-interactive")
    assert listing.exit_code == 0, listing.output
    assert "1. code-review\n" in listing.stdout  # The unstarred copy sorts first.
    assert "2. code-review ★" in listing.stdout and "4. code-review ★" in listing.stdout
    assert "3. release-notes\n" in listing.stdout

    everything = invoke("filter", "--starred", "--no-interactive")
    assert everything.exit_code == 0, everything.output
    assert everything.stdout.splitlines()[0] == "2 matching starred skills"
    assert "release-notes" not in everything.stdout
    assert everything.stdout.count("★") == 2
    for arguments, paths in (
        (["--starred"], ["review/SKILL.md", "review #?/SKILL.md"]),
        (["CODE maintain", "--starred"], ["review/SKILL.md", "review #?/SKILL.md"]),
        (
            ["--starred", "--repository", "https://github.com/ACME/skills.git"],
            ["review/SKILL.md"],
        ),
        (["notes", "--starred"], []),
        (
            ["CODE maintain"],
            [".agents/skills/review/SKILL.md", "review/SKILL.md", "review #?/SKILL.md"],
        ),
    ):
        result = invoke("filter", *arguments, "--json")
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert [skill["skill_path"] for skill in payload["skills"]] == paths
        assert payload["matching_count"] == len(paths)
        assert all(
            skill["starred"] is (skill["skill_path"] != ".agents/skills/review/SKILL.md")
            for skill in payload["skills"]
        )
    nonmatching = invoke("filter", "notes", "--starred", "--no-interactive")
    assert "No skills match the query" in nonmatching.stdout
    assert catalog.path.read_bytes() == before


@pytest.mark.parametrize("scope", ["missing", "unstarred", "unknown-repository"])
def test_filter_starred_empty_scopes_succeed(scope, scan_result):
    catalog = SQLiteCatalog(Settings.from_environment().database_path)
    arguments = ["filter", "--starred"]
    if scope != "missing":
        catalog.replace_repository(scan_result)
    if scope == "unknown-repository":
        catalog.set_starred(scan_result.repository, "review/SKILL.md", True)
        arguments += ["--repository", "https://github.com/unknown/repo"]
    result = invoke(*arguments, "--no-interactive")
    assert result.exit_code == 0, result.output
    assert "No starred skills in the selected scope" in result.stdout
    structured = invoke(*arguments, "--json")
    assert json.loads(structured.stdout) == {"matching_count": 0, "skills": []}
    assert catalog.path.exists() is (scope != "missing")


def test_similar_output_marks_source_and_locations(web_environment, similar_catalog):
    source = similar_catalog.source
    catalog = web_environment.catalog
    remote = similar_catalog.remote
    for skill in (source, remote):
        catalog.set_starred(skill.repository, skill.path, True)
    data = json.loads(invoke("similar", source.repository.url, source.path, "--json").stdout)
    assert data["source"]["starred"] is True
    assert [
        (location["skill_path"], location["starred"])
        for location in data["matches"][0]["locations"]
    ] == [
        (".agents/skills/review/SKILL.md", False),
        ("nested/copy/SKILL.md", False),
        ("review #?/SKILL.md", True),
    ]
    assert [location["starred"] for location in data["matches"][1]["locations"]] == [False]
    text = invoke("similar", source.repository.url, source.path, "--no-interactive").stdout
    lines = [line.strip() for line in text.splitlines()]
    assert lines[0] == "Similar to code-review ★ — 2 result groups"
    assert "1. code-review · 100%" in lines
    assert "other/skills · review #?/SKILL.md ★" in lines
    assert "Acme/skills · .agents/skills/review/SKILL.md" in lines


def test_help_lists_star_commands():
    assert all(command in invoke("--help").stdout for command in ("star", "unstar"))
    for command in ("star", "unstar"):
        help_text = Text.from_ansi(invoke(command, "--help").stdout).plain.casefold()
        assert "repository_url" in help_text and "skill_path" in help_text
    assert "--starred" in Text.from_ansi(invoke("filter", "--help").stdout).plain
