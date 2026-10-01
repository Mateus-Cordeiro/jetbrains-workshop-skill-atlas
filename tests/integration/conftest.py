"""Offline repository fixtures for full command-to-catalog integration tests."""

import base64
import json
import os
import sqlite3
import subprocess
from threading import Lock

import httpx
import pytest
from typer.testing import CliRunner

from skill_atlas import runtime
from skill_atlas.adapters.git import GitSnapshotReader
from skill_atlas.cli.app import create_app
from skill_atlas.errors import RepositoryError
from skill_atlas.models import Repository, Snapshot


class LocalRepository:
    def __init__(self, path, full_name, *, fork=False, archived=False):
        self.path = path
        self.identity = Repository.from_url(f"https://github.com/{full_name}")
        self.fork = fork
        self.archived = archived
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

    @property
    def empty(self):
        try:
            self.run("rev-parse", "--verify", "--quiet", "HEAD")
        except subprocess.CalledProcessError:
            return True
        return False

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
        self.truncated_repositories = set()
        self.failed_blob = None
        self.failed_trees = set()
        self.on_resolved = None
        self.on_tree = None
        self.on_fetch = None
        self.user_accounts = set()
        self.page_size = 100
        self.requests = []
        self.cancellations = []
        self._requests_lock = Lock()
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
            if kwargs.get("cancelled") is not None:
                self.cancellations.append(kwargs["cancelled"])
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
            output = run_git(reader, directory, *arguments)
            if arguments[0] == "fetch" and self.on_fetch:
                self.on_fetch(arguments[-1])
            return output

        monkeypatch.setattr(GitSnapshotReader, "__init__", initialize_git)
        monkeypatch.setattr(GitSnapshotReader, "_run", local_git)

    def add_repository(self, full_name="acme/skills", **flags):
        source = LocalRepository(self.root / f"source-{len(self.repositories)}", full_name, **flags)
        self.repositories[full_name] = source
        return source

    def requested(self, kind):
        """Recorded requests of one kind: graphql, repository, commit, tree, or blob."""
        return [path for recorded, path in self.requests if recorded == kind]

    def _record(self, kind, path):
        with self._requests_lock:
            self.requests.append((kind, path))

    def graphql(self, request):
        assert request.method == "POST"
        body = json.loads(request.content)
        variables = body["variables"]
        assert "repositoryOwner(login: $login)" in body["query"]
        assert variables["first"] == 100
        login = variables["login"]
        if login.lower() in self.user_accounts:
            return {"data": {"repositoryOwner": {"__typename": "User", "login": login}}}
        sources = sorted(
            (
                source
                for source in self.repositories.values()
                if source.identity.owner.lower() == login.lower()
            ),
            key=lambda source: source.identity.name.lower(),
        )
        if not sources:
            return {
                "data": {"repositoryOwner": None},
                "errors": [{"type": "NOT_FOUND", "path": ["repositoryOwner"]}],
            }
        # The fixture server chooses page boundaries; clients follow its cursors.
        start = int(variables["after"] or 0)
        page = sources[start : start + self.page_size]
        end = start + len(page)

        def node(source):
            branch = None
            if not source.empty:
                snapshot = source.snapshot()
                branch = {
                    "target": {"oid": snapshot.commit_sha, "tree": {"oid": snapshot.tree_sha}}
                }
            return {
                "nameWithOwner": source.identity.full_name,
                "isFork": source.fork,
                "isArchived": source.archived,
                "isEmpty": source.empty,
                "defaultBranchRef": branch,
            }

        return {
            "data": {
                "repositoryOwner": {
                    "__typename": "Organization",
                    "login": sources[0].identity.owner,
                    "repositories": {
                        "pageInfo": {"hasNextPage": end < len(sources), "endCursor": str(end)},
                        "nodes": [node(source) for source in page],
                    },
                }
            }
        }

    def handle(self, request):
        assert request.headers["Authorization"] == "Bearer integration-test-token"
        assert request.url.host == "api.github.com"
        if request.url.path == "/graphql":
            self._record("graphql", request.url.path)
            return httpx.Response(200, json=self.graphql(request))
        parts = request.url.path.strip("/").split("/")
        assert parts[0] == "repos"
        # GitHub owner and repository names are case-insensitive.
        source = next(
            source
            for source in self.repositories.values()
            if source.identity.full_name.lower() == "/".join(parts[1:3]).lower()
        )
        full_name = source.identity.full_name
        endpoint = parts[3:]
        kinds = {(): "repository", ("commits",): "commit", ("git", "trees"): "tree"}
        self._record(
            kinds.get(tuple(endpoint[:2]), kinds.get(tuple(endpoint[:1]), "blob")), full_name
        )
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
            if self.on_tree:
                response = self.on_tree(full_name)
                if response is not None:
                    return response
            if full_name in self.failed_trees:
                return httpx.Response(503)
            truncated = self.truncated or full_name in self.truncated_repositories
            entries = source.entries(endpoint[2])
            data = {"truncated": truncated, "tree": entries[:1] if truncated else entries}
        elif endpoint[:2] == ["git", "blobs"]:
            if endpoint[2] == self.failed_blob:
                return httpx.Response(503)
            content = source.run("cat-file", "blob", endpoint[2])
            data = {"encoding": "base64", "content": base64.b64encode(content).decode()}
        else:
            pytest.fail(f"Unexpected GitHub request: {request.url.path}")
        return httpx.Response(200, json=data)

    def scan(self, source):
        return self.scan_url(source.identity.url)

    def scan_url(self, url):
        return self.runner.invoke(
            create_app(), ["scan", url, "--no-interactive"], terminal_width=240
        )

    def rows(self):
        if not self.database.exists():
            return []
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


@pytest.fixture
def organization_harness(tmp_path, monkeypatch):
    """Organization scans choose truncated listings per repository."""
    return ScanHarness(tmp_path, monkeypatch)
