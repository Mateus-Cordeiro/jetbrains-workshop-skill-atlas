"""Real CLI/services with terminal streams and the blocking UI boundary substituted."""

import json
from dataclasses import replace
from io import StringIO
from types import SimpleNamespace

import pytest
from rich.text import Text
from typer.testing import CliRunner

from skill_atlas.cli.app import create_app
from skill_atlas.cli.output import presentation


class Stream(StringIO):
    def __init__(self, terminal):
        super().__init__()
        self.terminal = terminal

    def isatty(self):
        return self.terminal


@pytest.mark.parametrize("command", ["scan", "filter", "similar"])
@pytest.mark.parametrize(
    "stdin_tty, stdout_tty, term, options, interactive",
    [
        (True, True, "xterm-256color", [], True),
        (True, True, "xterm-256color", ["--no-interactive"], False),
        (False, True, "xterm-256color", [], False),
        (True, False, "xterm-256color", [], False),
        (False, False, "xterm-256color", [], False),
        (True, True, "dumb", [], False),
    ],
)
def test_commands_share_terminal_detection_and_opt_out(
    web_environment,
    scan_result,
    monkeypatch,
    command,
    stdin_tty,
    stdout_tty,
    term,
    options,
    interactive,
):
    source = scan_result.skills[0]
    web_environment.catalog.replace_repository(
        replace(scan_result, skills=(source, replace(source, path="copy/SKILL.md")))
    )
    before = web_environment.settings.database_path.read_bytes()
    monkeypatch.setenv("TERM", term)
    monkeypatch.setenv("FORCE_COLOR", "1")
    monkeypatch.setenv("COLUMNS", "240")
    monkeypatch.setattr(
        presentation,
        "sys",
        SimpleNamespace(stdin=Stream(stdin_tty), stdout=Stream(stdout_tty)),
    )
    opened = []
    monkeypatch.setattr(presentation.ResultsApp, "run", lambda app: opened.append(app))
    arguments = [command]
    if command in ("scan", "similar"):
        arguments += [source.repository.url]
    if command == "similar":
        arguments += [source.path]
    result = CliRunner().invoke(create_app(), [*arguments, *options])
    assert result.exit_code == 0, result.output
    assert result.stderr == ""
    assert bool(opened) is interactive
    if interactive:
        assert result.stdout == ""
        view = opened[0].result
        assert view.entries[0].skill.name == source.name
        assert view.entries[0].skill.description
        if command == "similar":
            assert view.entries[0].score == 100
            assert view.source == source
    else:
        text = Text.from_ansi(result.stdout).plain
        assert f"1. {source.name}" in text
        assert "Review changes." in text if command == "scan" else source.description in text
        repository_name = "acme/skills" if command == "scan" else source.repository.full_name
        assert repository_name in text and "/SKILL.md" in text
        assert "https://github.com/acme/skills/blob/" in text
        if not stdout_tty or term == "dumb":
            assert "\x1b" not in result.stdout
    if command != "scan":
        assert web_environment.settings.database_path.read_bytes() == before
        assert not web_environment.requests


@pytest.mark.parametrize("command", ["filter", "similar"])
@pytest.mark.parametrize("options", [[], ["--no-interactive"]])
def test_json_bypasses_interactive_view_on_terminals(
    web_environment,
    scan_result,
    monkeypatch,
    command,
    options,
):
    web_environment.catalog.replace_repository(scan_result)
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.setenv("FORCE_COLOR", "1")
    monkeypatch.setattr(
        presentation,
        "sys",
        SimpleNamespace(stdin=Stream(True), stdout=Stream(True)),
    )

    def unexpected(app):
        pytest.fail("JSON output must not open the interactive view")

    monkeypatch.setattr(presentation.ResultsApp, "run", unexpected)
    arguments = [command, "--json", *options]
    if command == "similar":
        arguments += [scan_result.repository.url, scan_result.skills[0].path]
    result = CliRunner().invoke(create_app(), arguments)
    assert result.exit_code == 0, result.output
    assert result.stderr == "" and "\x1b" not in result.stdout
    payload = json.loads(result.stdout)
    assert "matching_count" in payload if command == "filter" else "source" in payload


@pytest.mark.parametrize("command", ["scan", "filter", "similar"])
def test_help_exposes_shared_mode_option(command):
    result = CliRunner().invoke(create_app(), [command, "--help"])
    assert result.exit_code == 0
    assert "--no-interactive" in Text.from_ansi(result.stdout).plain
