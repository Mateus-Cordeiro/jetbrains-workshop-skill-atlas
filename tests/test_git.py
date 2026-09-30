import base64
import os
import subprocess
import sys
from pathlib import Path

import pytest

from skill_atlas import git
from skill_atlas.errors import CatalogError, RepositoryError
from skill_atlas.git import GitSnapshotReader
from skill_atlas.models import Snapshot
from skill_atlas.parsing import FrontmatterParser
from skill_atlas.readers import FallbackReader
from skill_atlas.scanner import Scanner


@pytest.fixture
def local_snapshot(tmp_path, repository):
    source = tmp_path / "source"
    source.mkdir()

    def run(*args):
        return (
            subprocess.run(["git", "-C", str(source), *args], capture_output=True, check=True)
            .stdout.decode()
            .strip()
        )

    run("init", "--quiet", "--template=")
    run("config", "user.name", "Test")
    run("config", "user.email", "test@example.invalid")
    run("config", "commit.gpgsign", "false")
    run("config", "core.hooksPath", os.devnull)
    run("config", "uploadpack.allowFilter", "true")
    run("config", "uploadpack.allowAnySHA1InWant", "true")
    content = b"---\nname: original\ndescription: Pinned snapshot.\n---\n"
    for name in ("SKILL.md", "nested space/skill/SKILL.md", "another/SKILL.md"):
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    (source / "lowercase").mkdir()
    (source / "lowercase" / "skill.md").write_bytes(content)
    (source / "ordinary.txt").write_text("This blob should not be downloaded.")
    if os.name != "nt":
        (source / "link").mkdir()
        (source / "link" / "SKILL.md").symlink_to("../SKILL.md")
    run("add", ".")
    run("commit", "--quiet", "-m", "Original")
    commit, tree = run("rev-parse", "HEAD"), run("rev-parse", "HEAD^{tree}")
    # Advance the branch: the adapter must still fetch the API-resolved commit.
    (source / "SKILL.md").write_text("Changed on the branch after resolution.")
    run("add", ".")
    run("commit", "--quiet", "-m", "Branch advanced")
    return source, Snapshot(repository, commit, tree), content


def local_reader(monkeypatch, source, temp_root):
    reader = GitSnapshotReader("private-test-token", temp_root=temp_root)
    original = reader._run

    def run(directory, *arguments):
        if arguments[:3] == ("remote", "add", "origin"):
            arguments = ("remote", "add", "origin", source.as_uri())
        return original(directory, *arguments)

    monkeypatch.setattr(reader, "_run", run)
    return reader


def test_partial_fetch_is_pinned_and_cleans_up_after_success(tmp_path, monkeypatch, local_snapshot):
    source, snapshot, content = local_snapshot
    temp_root = tmp_path / "temporary"
    temp_root.mkdir()
    with local_reader(monkeypatch, source, temp_root) as reader:
        assert not list(temp_root.iterdir())  # Lazy allocation.
        files = reader.skill_files(snapshot)
        assert {file.path for file in files} == {
            "SKILL.md",
            "nested space/skill/SKILL.md",
            "another/SKILL.md",
        }
        directory = next(temp_root.iterdir())
        assert not (directory / "SKILL.md").exists()  # Bare repository: no checkout.
        assert (directory / "shallow").read_text().strip() == snapshot.commit_sha
        missing = reader._run(
            directory, "rev-list", "--objects", "--missing=print", snapshot.commit_sha
        )
        assert b"?" in missing  # The unrelated source blobs were not downloaded.
        assert all(reader.read_file(snapshot, file) == content for file in files)
        assert b"?" in reader._run(
            directory, "rev-list", "--objects", "--missing=print", snapshot.commit_sha
        )
        assert "private-test-token" not in (directory / "config").read_text()
        assert "Authorization" not in (directory / "config").read_text()
    assert not list(temp_root.iterdir())


@pytest.mark.parametrize("failure", [RepositoryError("failed"), KeyboardInterrupt()])
def test_fetch_failure_and_interrupt_remove_partial_repository(
    tmp_path, monkeypatch, repository, failure
):
    reader = GitSnapshotReader(None, temp_root=tmp_path)

    def fail(directory, *arguments):
        assert directory.exists()
        (directory / "partial-download").write_text("partial")
        raise failure

    monkeypatch.setattr(reader, "_run", fail)
    with pytest.raises(type(failure)), reader:
        reader.skill_files(Snapshot(repository, "a" * 40, "b" * 40))
    assert not list(tmp_path.iterdir())


def test_catalog_failure_also_removes_git_files(tmp_path, monkeypatch, local_snapshot):
    source, snapshot, _ = local_snapshot
    temp_root = tmp_path / "temporary"
    temp_root.mkdir()

    class Primary:
        def resolve(self, repository):
            return snapshot

        def skill_files(self, snapshot):
            from skill_atlas.errors import IncompleteListingError

            raise IncompleteListingError("truncated")

    class FailingCatalog:
        def replace_repository(self, result):
            raise CatalogError("disk failure")

    with pytest.raises(CatalogError), local_reader(monkeypatch, source, temp_root) as reader:
        Scanner(FallbackReader(Primary(), reader), FrontmatterParser(), FailingCatalog()).scan(
            snapshot.repository
        )
    assert not list(temp_root.iterdir())


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


@pytest.mark.parametrize("interrupt", [False, True])
def test_timeout_or_interrupt_stops_git_before_cleanup(
    tmp_path, monkeypatch, repository, interrupt
):
    real_popen = subprocess.Popen
    processes = []
    paths = []

    def sleeping_git(command, **kwargs):
        paths.append(Path(command[2]))
        process = real_popen([sys.executable, "-c", "import time; time.sleep(60)"], **kwargs)
        processes.append(process)
        if interrupt:
            communicate = process.communicate
            first = True

            def interrupted(*args, **kwargs):
                nonlocal first
                if first:
                    first = False
                    raise KeyboardInterrupt()
                return communicate(*args, **kwargs)

            monkeypatch.setattr(process, "communicate", interrupted)
        return process

    monkeypatch.setattr(git.subprocess, "Popen", sleeping_git)
    with (
        pytest.raises(KeyboardInterrupt if interrupt else RepositoryError),
        GitSnapshotReader(None, timeout=0.05, temp_root=tmp_path) as reader,
    ):
        reader.skill_files(Snapshot(repository, "a" * 40, "b" * 40))
    assert all(process.poll() is not None for process in processes)
    assert all(not path.exists() for path in paths)
    assert not list(tmp_path.iterdir())
