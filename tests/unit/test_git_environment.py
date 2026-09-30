import base64

import pytest

from skill_atlas import git
from skill_atlas.errors import RepositoryError
from skill_atlas.git import GitSnapshotReader


def test_credentials_are_process_local_and_repository_overrides_are_removed(monkeypatch):
    monkeypatch.setenv("GIT_DIR", "/some/user/checkout")
    monkeypatch.setenv("GIT_TRACE_CURL", "1")
    environment = git._git_environment("secret-token")
    assert "GIT_DIR" not in environment
    assert "GIT_TRACE_CURL" not in environment
    assert environment["GIT_TERMINAL_PROMPT"] == "0"
    configs = [
        (environment[f"GIT_CONFIG_KEY_{i}"], environment[f"GIT_CONFIG_VALUE_{i}"])
        for i in range(int(environment["GIT_CONFIG_COUNT"]))
    ]
    expected = base64.b64encode(b"x-access-token:secret-token").decode()
    assert ("http.https://github.com/.extraheader", "Authorization: Basic " + expected) in configs


def test_missing_git_has_actionable_error(tmp_path, monkeypatch):
    def missing(*args, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(git.subprocess, "Popen", missing)
    with GitSnapshotReader(None, temp_root=tmp_path) as reader:
        with pytest.raises(RepositoryError, match="Install Git"):
            reader._run(tmp_path, "version")
