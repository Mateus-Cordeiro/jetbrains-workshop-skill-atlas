import subprocess
from types import SimpleNamespace

import pytest

from skill_atlas import auth


@pytest.mark.parametrize(
    ("environment", "expected"),
    [
        ({"GH_TOKEN": " first ", "GITHUB_TOKEN": "second"}, "first"),
        ({"GITHUB_TOKEN": "second"}, "second"),
        ({"GH_TOKEN": " ", "GITHUB_TOKEN": "second"}, "second"),
    ],
)
def test_environment_credentials_take_precedence(monkeypatch, environment, expected):
    def unexpected(*args, **kwargs):
        pytest.fail("gh should not run when a token is provided")

    monkeypatch.setattr(auth.subprocess, "run", unexpected)
    assert auth.github_token(environment) == expected


def test_github_cli_fallback(monkeypatch):
    def run(command, **kwargs):
        assert command == ["gh", "auth", "token", "--hostname", "github.com"]
        assert kwargs["capture_output"]
        assert kwargs["timeout"] == 5
        return SimpleNamespace(returncode=0, stdout="test-token\n")

    monkeypatch.setattr(auth.subprocess, "run", run)
    assert auth.github_token({}) == "test-token"


@pytest.mark.parametrize("failure", [FileNotFoundError(), subprocess.TimeoutExpired("gh", 5)])
def test_unavailable_github_cli_allows_anonymous_access(monkeypatch, failure):
    def run(*args, **kwargs):
        raise failure

    monkeypatch.setattr(auth.subprocess, "run", run)
    assert auth.github_token({}) is None


def test_unauthenticated_github_cli_does_not_use_stdout(monkeypatch):
    monkeypatch.setattr(
        auth.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="error"),
    )
    assert auth.github_token({}) is None
