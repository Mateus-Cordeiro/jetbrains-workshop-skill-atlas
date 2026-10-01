import json
import sqlite3
import subprocess
from dataclasses import replace
from html.parser import HTMLParser
from io import StringIO
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from rich.text import Text
from typer.testing import CliRunner

from skill_atlas import runtime
from skill_atlas.adapters.storage.sqlite import SQLiteCatalog
from skill_atlas.cli.app import create_app
from skill_atlas.cli.commands import filter as filter_command
from skill_atlas.config import Settings
from skill_atlas.models import Repository, ScanResult

runner = CliRunner()


@pytest.fixture
def catalog(scan_result):
    catalog = SQLiteCatalog(Settings.from_environment().database_path)
    review = scan_result.skills[0]
    catalog.replace_repository(
        replace(
            scan_result,
            skills=(
                *scan_result.skills,
                replace(review, path=".agents/skills/review/SKILL.md"),
                replace(
                    review,
                    path="SKILL.md",
                    name="Straße",
                    description="Maintain 100% café_name and .* code.",
                ),
            ),
        )
    )
    remote = replace(
        review,
        repository=Repository("zebra", "skills"),
        path="review #?/SKILL.md",
        commit_sha="b" * 40,
    )
    catalog.replace_repository(ScanResult(remote.repository, remote.commit_sha, (remote,)))
    return catalog


class SkillLinks(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.identities = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and attrs.get("class") in {"catalog-skill", "skill-link"}:
            query = parse_qs(urlsplit(attrs["href"]).query)
            self.identities.append((query["repository_url"][0], query["skill_path"][0]))


@pytest.mark.parametrize("scoped", [False, True])
@pytest.mark.parametrize(
    "query, global_count, scoped_count",
    [
        ("", 5, 4),
        (" \t\n ", 5, 4),
        ("CODE maintain", 4, 3),
        ("STRASSE CAFÉ", 1, 1),
        ("100% _name", 1, 1),
        (".*", 1, 1),
        ("  NOTES\nDraft ", 1, 1),
        ("review notes", 0, 0),
        ("SKILL.md", 0, 0),
        ("acme", 0, 0),
        ("body-only", 0, 0),
    ],
)
def test_cli_and_web_return_same_ordered_identities(
    catalog, web_environment, scoped, query, global_count, scoped_count
):
    before = catalog.path.read_bytes()
    arguments = ["filter", query, "--json"]
    repository_url = "https://github.com/acme/skills"
    if scoped:
        arguments += ["--repository", "https://github.com:443/ACME/skills.git/"]
    result = runner.invoke(create_app(), arguments)
    assert result.exit_code == 0, result.output
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert payload["matching_count"] == (scoped_count if scoped else global_count)
    identities = [(row["repository_url"], row["skill_path"]) for row in payload["skills"]]
    assert len(identities) == payload["matching_count"]
    with TestClient(web_environment.app, base_url="http://127.0.0.1") as client:
        if scoped:
            page = client.get(
                "/fragments/skills", params={"repository_url": repository_url, "q": query}
            )
            assert page.status_code == 200
            web_identities = SkillLinks(page.text).identities
        elif query.strip():
            page = client.get("/", params={"q": query})
            assert page.status_code == 200
            web_identities = SkillLinks(page.text).identities
        else:
            # Empty homepage queries keep groups collapsed; compare their expanded entries.
            web_identities = []
            for repository in catalog.repositories():
                page = client.get(
                    "/fragments/repository-skills",
                    params={"repository_url": repository.repository.url, "q": query},
                )
                assert page.status_code == 200
                web_identities.extend(SkillLinks(page.text).identities)
        assert identities == web_identities
    assert catalog.path.read_bytes() == before
    assert not web_environment.requests


def test_filter_lists_all_skills_offline_without_writes_or_credentials(catalog, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("Filtering must not resolve credentials, use subprocesses, or create a client")

    monkeypatch.setattr(runtime, "github_token", unexpected)
    monkeypatch.setattr(runtime.httpx, "Client", unexpected)
    monkeypatch.setattr(subprocess, "Popen", unexpected)
    monkeypatch.setenv("FORCE_COLOR", "1")
    monkeypatch.setenv("COLUMNS", "240")
    before = catalog.path.read_bytes()
    result = runner.invoke(create_app(), ["filter"])
    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines()[0] == "5 matching skills"
    for index, skill in enumerate(catalog.skills(), start=1):
        assert f"{index}. {skill.name}" in result.stdout
        assert skill.repository.full_name in result.stdout
        assert skill.path in result.stdout
        assert skill.description in result.stdout
        assert skill.url in result.stdout
    assert "review%20%23%3F/SKILL.md" in result.stdout
    assert "\x1b" not in result.stdout
    assert result.stderr == ""
    assert catalog.path.read_bytes() == before


def test_json_round_trips_metadata_and_commits_on_a_terminal(catalog, monkeypatch):
    original = catalog.skills()[0]
    skill = replace(
        original,
        name='Straße "[bold]name[/bold]"',
        description="Literal [red]text[/red].\nUnicode café\t\x1b[31m\x07",
        path="path #?/SKILL.md",
    )
    catalog.replace_repository(ScanResult(skill.repository, skill.commit_sha, (skill,)))

    class Terminal(StringIO):
        def isatty(self):
            return True

    terminal = Terminal()
    monkeypatch.setattr(filter_command, "sys", SimpleNamespace(stdout=terminal))
    monkeypatch.setenv("FORCE_COLOR", "1")
    result = runner.invoke(create_app(), ["filter", "--json", "--repository", skill.repository.url])
    assert result.exit_code == 0, result.output
    output = terminal.getvalue()
    assert result.stdout == result.stderr == ""
    assert output.endswith("\n")
    assert "\x1b" not in output and "\x07" not in output
    assert json.loads(output) == {
        "matching_count": 1,
        "skills": [
            {
                "repository_url": skill.repository.url,
                "repository_name": skill.repository.full_name,
                "skill_path": skill.path,
                "skill_name": skill.name,
                "description": skill.description,
                "commit_sha": skill.commit_sha,
                "url": skill.url,
                "starred": False,
            }
        ],
    }


@pytest.mark.parametrize("state", ["missing", "empty", "unknown", "nonmatching"])
def test_empty_states_succeed_without_creating_or_changing_catalog(state, scan_result):
    catalog = SQLiteCatalog(Settings.from_environment().database_path)
    arguments = ["filter", "unmatched"]
    if state != "missing":
        catalog.replace_repository(
            replace(scan_result, skills=() if state == "empty" else scan_result.skills)
        )
    if state == "unknown":
        arguments += ["--repository", "https://github.com/unknown/repo"]
    before = catalog.path.read_bytes() if catalog.path.exists() else None
    result = runner.invoke(create_app(), arguments)
    assert result.exit_code == 0, result.output
    message = (
        "No skills match the query"
        if state == "nonmatching"
        else "No saved skills in the selected scope"
    )
    assert message in result.stdout
    structured = runner.invoke(create_app(), [*arguments, "--json"])
    assert structured.exit_code == 0
    assert json.loads(structured.stdout) == {"matching_count": 0, "skills": []}
    assert (catalog.path.read_bytes() if catalog.path.exists() else None) == before


@pytest.mark.parametrize("json_output", [False, True])
@pytest.mark.parametrize("state", ["corrupt", "unsupported", "newer", "unreadable"])
def test_catalog_errors_go_only_to_stderr_without_modification(catalog, state, json_output):
    if state == "corrupt":
        catalog.path.write_bytes(b"not a database")
    elif state == "unreadable":
        # A directory cannot be opened as a SQLite database, even when tests run as root.
        catalog.path.unlink()
        catalog.path.mkdir()
    else:
        with sqlite3.connect(catalog.path) as connection:
            connection.execute(f"PRAGMA user_version = {0 if state == 'unsupported' else 99}")
    before = catalog.path.read_bytes() if catalog.path.is_file() else None
    result = runner.invoke(create_app(), ["filter", *(["--json"] if json_output else [])])
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "Error:" in result.stderr
    assert "No skills" not in result.stderr
    if before is not None:
        assert catalog.path.read_bytes() == before
    else:
        assert catalog.path.is_dir() and not list(catalog.path.iterdir())


def test_filter_help_and_invalid_usage():
    help_result = runner.invoke(create_app(), ["filter", "--help"])
    assert help_result.exit_code == 0
    help_text = Text.from_ansi(help_result.stdout).plain
    assert "--repository" in help_text and "--json" in help_text and "QUERY" in help_text
    assert "filter" in runner.invoke(create_app(), ["--help"]).stdout
    for args in (
        ["--repository", "https://token:secret@github.com/acme/skills"],
        ["--repository", ""],
        ["unquoted", "terms"],
        ["--unknown"],
    ):
        result = runner.invoke(create_app(), ["filter", *args])
        assert result.exit_code == 2
        assert result.stdout == ""
        assert "secret" not in result.stderr
    assert not Settings.from_environment().database_path.exists()


def test_filter_reads_complete_snapshots_during_repository_replacement(catalog):
    original = json.loads(runner.invoke(create_app(), ["filter", "--json"]).stdout)
    with sqlite3.connect(catalog.path) as writer:
        writer.execute("BEGIN IMMEDIATE")
        writer.execute("DELETE FROM skills WHERE repository_url = 'https://github.com/acme/skills'")
        # A reader during an unfinished replacement must still see the old complete result.
        during = runner.invoke(create_app(), ["filter", "--json"])
        assert during.exit_code == 0
        assert json.loads(during.stdout) == original
        scope = runtime.create_catalog_browser(Settings.from_environment()).filter("CODE maintain")
        assert scope.total_count == 5 and len(scope.matches) == 4
    after = runner.invoke(create_app(), ["filter", "--json"])
    assert after.exit_code == 0
    remaining = json.loads(after.stdout)
    assert remaining == {"matching_count": 1, "skills": original["skills"][-1:]}
    scope = runtime.create_catalog_browser(Settings.from_environment()).filter("CODE maintain")
    assert scope.total_count == len(scope.matches) == 1
