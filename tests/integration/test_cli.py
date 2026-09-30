import base64
import sqlite3

import httpx
from rich.text import Text
from typer.testing import CliRunner

from skill_atlas import runtime
from skill_atlas.cli import create_app

runner = CliRunner()


def configure_http(monkeypatch, handler):
    client_class = httpx.Client
    monkeypatch.setattr(runtime, "github_token", lambda: "private-test-token")
    monkeypatch.setattr(
        runtime.httpx,
        "Client",
        lambda **kwargs: client_class(**kwargs, transport=httpx.MockTransport(handler)),
    )


def test_help_exposes_subcommand():
    result = runner.invoke(create_app(), ["--help"])
    assert result.exit_code == 0
    assert "scan" in Text.from_ansi(result.stdout).plain
    result = runner.invoke(create_app(), ["scan", "--help"])
    assert result.exit_code == 0
    # CI terminal styling can insert ANSI sequences inside an option's name.
    assert "--no-interactive" in Text.from_ansi(result.stdout).plain


def test_bad_url_has_usage_exit_code_and_no_token_in_error(tmp_path, monkeypatch):
    database = tmp_path / "catalog.sqlite3"
    monkeypatch.setenv("SKILL_ATLAS_DB", str(database))
    result = runner.invoke(create_app(), ["scan", "https://token:secret@github.com/acme/skills"])
    assert result.exit_code == 2
    assert "secret" not in result.output
    assert not database.exists()


def test_complete_command_scans_persists_and_prints_plain_output(tmp_path, monkeypatch):
    database = tmp_path / "catalog.sqlite3"
    monkeypatch.setenv("SKILL_ATLAS_DB", str(database))

    def handler(request):
        assert request.headers["Authorization"] == "Bearer private-test-token"
        path = request.url.path
        if path == "/repos/acme/skills":
            data = {"full_name": "acme/skills", "default_branch": "main"}
        elif "/commits/" in path:
            data = {"sha": "a" * 40, "commit": {"tree": {"sha": "b" * 40}}}
        elif "/git/trees/" in path:
            data = {
                "truncated": False,
                "tree": [{"path": "SKILL.md", "type": "blob", "mode": "100644", "sha": "c" * 40}],
            }
        else:
            content = b"---\nname: code-review\ndescription: Review changes.\n---"
            data = {"encoding": "base64", "content": base64.b64encode(content).decode()}
        return httpx.Response(200, json=data)

    configure_http(monkeypatch, handler)
    # CliRunner is not a TTY: redirected output must work without an explicit flag.
    for _ in range(2):
        result = runner.invoke(create_app(), ["scan", "https://github.com/acme/skills"])
        assert result.exit_code == 0, result.output
        assert result.stdout.splitlines()[0] == "acme/skills — 1 skill"
        assert "1. code-review" in result.stdout
        assert "Review changes." in result.stdout
        assert "https://github.com/acme/skills/blob/" in result.stdout
        assert "\x1b" not in result.stdout
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT count(*) FROM skills").fetchone()[0] == 1
        assert connection.execute("SELECT commit_sha FROM skills").fetchone()[0] == "a" * 40


def test_access_failure_has_operational_exit_code(tmp_path, monkeypatch):
    database = tmp_path / "catalog.sqlite3"
    monkeypatch.setenv("SKILL_ATLAS_DB", str(database))
    configure_http(monkeypatch, lambda request: httpx.Response(404))
    result = runner.invoke(
        create_app(), ["scan", "https://github.com/acme/private", "--no-interactive"]
    )
    assert result.exit_code == 1
    assert "private repository access" in " ".join(result.stderr.split())
    assert result.stdout == ""
    assert not database.exists()


def test_command_registration_is_extensible():
    app = create_app()

    @app.command()
    def another():
        print("another command")

    result = runner.invoke(app, ["another"])
    assert result.exit_code == 0
    assert result.stdout.strip() == "another command"
