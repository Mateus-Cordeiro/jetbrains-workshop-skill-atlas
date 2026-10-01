import os
import subprocess
import sys
from pathlib import Path

import pytest

from skill_atlas.adapters import git
from skill_atlas.adapters.frontmatter import FrontmatterParser
from skill_atlas.adapters.git import GitSnapshotReader
from skill_atlas.application.reader_fallback import FallbackReader
from skill_atlas.application.scan import Scanner
from skill_atlas.errors import CatalogError, RepositoryError
from skill_atlas.models import Snapshot


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


@pytest.mark.parametrize("cancel_before_start", [False, True])
def test_cancellation_stops_running_git_and_cleans_up(
    tmp_path, monkeypatch, repository, cancel_before_start
):
    from threading import Event, Timer
    from time import monotonic

    from skill_atlas.errors import ScanCancelled

    real_popen = subprocess.Popen
    processes = []

    def sleeping_git(command, **kwargs):
        process = real_popen([sys.executable, "-c", "import time; time.sleep(60)"], **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(git.subprocess, "Popen", sleeping_git)
    cancelled = Event()
    if cancel_before_start:
        cancelled.set()
    timer = Timer(0.1, cancelled.set)
    timer.start()
    started = monotonic()
    try:
        with (
            pytest.raises(ScanCancelled),
            GitSnapshotReader(None, timeout=30, temp_root=tmp_path, cancelled=cancelled) as reader,
        ):
            reader.skill_files(Snapshot(repository, "a" * 40, "b" * 40))
    finally:
        timer.cancel()
    # Cancellation does not wait for Git's own timeout.
    assert monotonic() - started < 5
    assert len(processes) == (0 if cancel_before_start else 1)
    assert all(process.poll() is not None for process in processes)
    assert not list(tmp_path.iterdir())


def test_cancellable_git_still_enforces_its_timeout(tmp_path, monkeypatch, repository):
    from threading import Event

    real_popen = subprocess.Popen
    monkeypatch.setattr(
        git.subprocess,
        "Popen",
        lambda command, **kwargs: real_popen(
            [sys.executable, "-c", "import time; time.sleep(60)"], **kwargs
        ),
    )
    with (
        pytest.raises(RepositoryError, match="timed out"),
        GitSnapshotReader(None, timeout=0.3, temp_root=tmp_path, cancelled=Event()) as reader,
    ):
        reader.skill_files(Snapshot(repository, "a" * 40, "b" * 40))
    assert not list(tmp_path.iterdir())


def test_truncated_bundle_uses_exact_commit_and_includes_supporting_files(
    tmp_path, monkeypatch, local_snapshot
):
    import httpx

    from skill_atlas.adapters.bundles import RepositoryBundles
    from skill_atlas.adapters.github import GitHubReader
    from skill_atlas.adapters.installation.transactions import LocalProjects
    from skill_atlas.adapters.storage.sqlite import SQLiteCatalog
    from skill_atlas.application.installations import Installations
    from skill_atlas.models import ScanResult, Skill

    source, snapshot, content = local_snapshot
    requests = []

    def handler(request):
        requests.append(request)
        if "/commits/" in request.url.path:
            assert request.url.path.endswith(snapshot.commit_sha)
            return httpx.Response(
                200,
                json={"sha": snapshot.commit_sha, "commit": {"tree": {"sha": snapshot.tree_sha}}},
            )
        return httpx.Response(200, json={"truncated": True, "tree": []})

    project = tmp_path / "project"
    project.mkdir()
    temporary = tmp_path / "temporary"
    temporary.mkdir()
    catalog = SQLiteCatalog(tmp_path / "catalog.sqlite3")
    skill = Skill(snapshot.repository, "SKILL.md", "root-skill", "Root.", snapshot.commit_sha)
    catalog.replace_repository(ScanResult(snapshot.repository, snapshot.commit_sha, (skill,)))
    with (
        local_reader(monkeypatch, source, temporary) as git,
        httpx.Client(
            base_url="https://api.github.com", transport=httpx.MockTransport(handler)
        ) as client,
    ):
        service = Installations(catalog, LocalProjects())
        service.install(
            project,
            snapshot.repository,
            "SKILL.md",
            "claude",
            RepositoryBundles(GitHubReader(client), git),
        )
    target = project / ".claude/skills/root-skill"
    assert (target / "SKILL.md").read_bytes() == content
    assert (target / "ordinary.txt").read_text() == "This blob should not be downloaded."
    assert (target / "nested space/skill/SKILL.md").read_bytes() == content
    assert not (target / "link").exists()
    assert not list(temporary.iterdir())
    assert len(requests) == 2


def test_scan_still_ignores_unrelated_non_utf8_filenames(tmp_path, monkeypatch, local_snapshot):
    source, snapshot, _ = local_snapshot

    def command(*arguments, data=None):
        return subprocess.run(
            ["git", "-C", str(source), *arguments], input=data, check=True, capture_output=True
        ).stdout

    # Git can represent non-UTF-8 paths even on filesystems (such as APFS) that cannot.
    blob = command("hash-object", "-w", "--stdin", data=b"unrelated").strip()
    listing = command("ls-tree", "-z", "HEAD")
    listing += b"100644 blob " + blob + b"\tunrelated-\xff.bin\0"
    tree = command("mktree", "-z", data=listing).decode().strip()
    commit = command("commit-tree", tree, "-p", "HEAD", "-m", "Unrelated filename").decode().strip()
    command("update-ref", "refs/heads/unusual", commit)
    temporary = tmp_path / "snapshots"
    temporary.mkdir()
    with local_reader(monkeypatch, source, temporary) as reader:
        files = reader.skill_files(Snapshot(snapshot.repository, commit, tree))
        assert len(files) == 3
