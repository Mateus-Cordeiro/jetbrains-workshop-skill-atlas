"""Offline repository fixtures for full command-to-catalog integration tests."""

import base64
import os
import sqlite3
import subprocess

import httpx
import pytest
from typer.testing import CliRunner

from skill_atlas import runtime
from skill_atlas.cli import create_app
from skill_atlas.errors import RepositoryError
from skill_atlas.git import GitSnapshotReader
from skill_atlas.models import Repository, Snapshot


class LocalRepository:
    def __init__(self, path, full_name):
        self.path = path
        self.identity = Repository.from_url(f"https://github.com/{full_name}")
        self.path.mkdir()
        self.run("init", "--quiet", "--template=", "--initial-branch=main")
        for key, value in {
            "user.name": "Integration Test",
            "user.email": "tests@example.invalid",
            "commit.gpgsign": "false",
            "core.hooksPath": os.devnull,
            "uploadpack.allowFilter": "true",
            "uploadpack.allowAnySHA1InWant": "true",
        }.items():
            self.run("config", key, value)

    def run(self, *arguments):
        environment = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
        return subprocess.run(
            ["git", "-C", str(self.path), *arguments],
            capture_output=True,
            check=True,
            env=environment,
            timeout=10,
        ).stdout

    def write(self, path, content):
        target = self.path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content if isinstance(content, bytes) else content.encode())

    def commit(self):
        self.run("add", "--all")
        self.run("commit", "--quiet", "--allow-empty", "-m", "Fixture snapshot")
        return self.snapshot()

    def snapshot(self):
        return Snapshot(
            self.identity,
            self.run("rev-parse", "HEAD").decode().strip(),
            self.run("rev-parse", "HEAD^{tree}").decode().strip(),
        )

    def entries(self, tree):
        entries = []
        for record in self.run("ls-tree", "-r", "-z", tree).split(b"\0"):
            if record:
                metadata, path = record.split(b"\t", 1)
                mode, kind, sha = metadata.decode().split()
                entries.append({"path": path.decode(), "mode": mode, "type": kind, "sha": sha})
        return entries


class ScanHarness:
    def __init__(self, tmp_path, monkeypatch):
        self.root = tmp_path
        self.database = tmp_path / "catalog.sqlite3"
        self.git_temporary = tmp_path / "git-temporary"
        self.git_temporary.mkdir()
        self.repositories = {}
        self.git_fetches = []
        self.truncated = False
        self.failed_blob = None
        self.on_resolved = None
        self.runner = CliRunner()

        client_class = httpx.Client
        monkeypatch.setattr(runtime, "github_token", lambda: "integration-test-token")
        monkeypatch.setenv("SKILL_ATLAS_DB", str(self.database))
        # Rich reads COLUMNS independently of Typer's terminal_width argument.
        monkeypatch.setenv("COLUMNS", "240")
        monkeypatch.setattr(
            runtime.httpx,
            "Client",
            lambda **kwargs: client_class(**kwargs, transport=httpx.MockTransport(self.handle)),
        )
        initialize = GitSnapshotReader.__init__
        run_git = GitSnapshotReader._run

        def initialize_git(reader, token, **kwargs):
            initialize(reader, token, **kwargs, temp_root=self.git_temporary)

        def local_git(reader, directory, *arguments):
            if arguments[:3] == ("remote", "add", "origin"):
                # Only the remote address is substituted. All Git operations,
                # commit selection, blob reads, and cleanup are production code.
                source = next(
                    repo
                    for repo in self.repositories.values()
                    if repo.identity.url + ".git" == arguments[3]
                )
                arguments = ("remote", "add", "origin", source.path.as_uri())
            if arguments[0] == "fetch":
                self.git_fetches.append(arguments[-1])
            if arguments[:2] == ("cat-file", "blob") and arguments[2] == self.failed_blob:
                raise RepositoryError("Fixture blob retrieval failed")
            return run_git(reader, directory, *arguments)

        monkeypatch.setattr(GitSnapshotReader, "__init__", initialize_git)
        monkeypatch.setattr(GitSnapshotReader, "_run", local_git)

    def add_repository(self, full_name="acme/skills"):
        source = LocalRepository(self.root / f"source-{len(self.repositories)}", full_name)
        self.repositories[full_name] = source
        return source

    def handle(self, request):
        assert request.headers["Authorization"] == "Bearer integration-test-token"
        assert request.url.host == "api.github.com"
        parts = request.url.path.strip("/").split("/")
        assert parts[0] == "repos"
        source = self.repositories["/".join(parts[1:3])]
        endpoint = parts[3:]
        if not endpoint:
            data = {"full_name": source.identity.full_name, "default_branch": "main"}
        elif endpoint == ["commits", "main"]:
            snapshot = source.snapshot()
            data = {"sha": snapshot.commit_sha, "commit": {"tree": {"sha": snapshot.tree_sha}}}
            if self.on_resolved:
                callback, self.on_resolved = self.on_resolved, None
                callback()
        elif endpoint[:2] == ["git", "trees"]:
            assert request.url.params["recursive"] == "1"
            entries = source.entries(endpoint[2])
            data = {"truncated": self.truncated, "tree": entries[:1] if self.truncated else entries}
        elif endpoint[:2] == ["git", "blobs"]:
            if endpoint[2] == self.failed_blob:
                return httpx.Response(503)
            content = source.run("cat-file", "blob", endpoint[2])
            data = {"encoding": "base64", "content": base64.b64encode(content).decode()}
        else:
            pytest.fail(f"Unexpected GitHub request: {request.url.path}")
        return httpx.Response(200, json=data)

    def scan(self, source):
        return self.runner.invoke(
            create_app(),
            ["scan", source.identity.url, "--no-interactive"],
            terminal_width=240,
        )

    def rows(self):
        with sqlite3.connect(self.database) as connection:
            connection.row_factory = sqlite3.Row
            return [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM skills ORDER BY repository_url, skill_name, skill_path"
                )
            ]


@pytest.fixture(params=[False, True], ids=["github-api", "git-fallback"])
def scan_harness(tmp_path, monkeypatch, request):
    harness = ScanHarness(tmp_path, monkeypatch)
    harness.truncated = request.param
    return harness
