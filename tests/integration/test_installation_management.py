"""Real bundle transport, filesystem, manifest, catalog, CLI and Web parity."""

import base64
import hashlib
import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from skill_atlas import runtime
from skill_atlas.adapters.installation.filesystem import ProjectFiles
from skill_atlas.adapters.installation.records import MANIFEST, ProjectRecords
from skill_atlas.adapters.installation.transactions import (
    BACKUP,
    JOURNAL,
    STAGE,
    ProjectTransaction,
)
from skill_atlas.adapters.projects import project_path
from skill_atlas.adapters.storage.sqlite import SQLiteCatalog
from skill_atlas.cli.app import create_app
from skill_atlas.config import Settings
from skill_atlas.installation import InstallationError
from skill_atlas.models import Repository, ScanResult, Skill

HEADERS = {"Origin": "http://127.0.0.1", "X-Atlas-Request": "1"}


@pytest.fixture
def installation_env(tmp_path, monkeypatch):
    project = tmp_path / "project with spaces"
    project.mkdir()
    settings = Settings(tmp_path / "catalog.sqlite3")
    catalog = SQLiteCatalog(settings.database_path)
    repository = Repository("acme", "private-skills")
    state = SimpleNamespace(
        project=project,
        settings=settings,
        catalog=catalog,
        requests=[],
        source="nested/review/SKILL.md",
        outside_paths=["outside.txt"],
        fail=False,
    )
    state.revisions = {
        "a" * 40: {
            "SKILL.md": (b"---\nname: review\ndescription: Review.\n---\n", False),
            "scripts/run.sh": (b"#!/bin/sh\necho never-executed\n", True),
            "assets/raw.bin": (b"\x00\xff\x80\r\n", False),
        },
        "b" * 40: {
            "SKILL.md": (b"---\nname: review\ndescription: Updated.\n---\n", False),
            "new/data.bin": (b"\x00updated\xff", True),
        },
    }
    state.skill = Skill(repository, state.source, "review", "Review.", "a" * 40)

    def seed(commit="a" * 40, source=None):
        state.skill = replace(state.skill, commit_sha=commit, path=source or state.source)
        state.source = state.skill.path
        catalog.replace_repository(ScanResult(repository, commit, (state.skill,)))
        return state.skill

    state.seed = seed
    seed()
    blobs = {}

    def handler(request):
        state.requests.append(request)
        assert request.headers["Authorization"] == "Bearer private-fixture-token"
        path = request.url.path
        if state.fail:
            return httpx.Response(503)
        if "/commits/" in path:
            commit = path.rsplit("/", 1)[-1]
            assert commit in state.revisions  # No branch or HEAD request.
            return httpx.Response(200, json={"sha": commit, "commit": {"tree": {"sha": commit}}})
        if "/git/trees/" in path:
            commit = path.rsplit("/", 1)[-1]
            root = state.source.removesuffix("SKILL.md")
            tree = []
            for name, (content, executable) in state.revisions[commit].items():
                sha = hashlib.sha1(content).hexdigest()
                blobs[sha] = content
                tree.append(
                    dict(
                        path=root + name,
                        type="blob",
                        mode="100755" if executable else "100644",
                        sha=sha,
                    )
                )
            # Never retrieve these entries or follow their targets.
            tree += [
                dict(path=root + "link", type="blob", mode="120000", sha="c" * 40),
                dict(path=root + "submodule", type="commit", mode="160000", sha="d" * 40),
            ]
            if root:
                tree.extend(
                    dict(path=path, type="blob", mode="100644", sha="e" * 40)
                    for path in state.outside_paths
                )
            return httpx.Response(200, json={"truncated": False, "tree": tree})
        sha = path.rsplit("/", 1)[-1]
        return httpx.Response(
            200, json={"encoding": "base64", "content": base64.b64encode(blobs[sha]).decode()}
        )

    client = httpx.Client
    monkeypatch.setattr(runtime, "github_token", lambda: "private-fixture-token")
    monkeypatch.setattr(
        runtime.httpx, "Client", lambda **kw: client(**kw, transport=httpx.MockTransport(handler))
    )
    state.service = runtime.create_installations(settings)
    state.reader = runtime.LazyBundleReader(settings)
    state.install = lambda **kw: state.service.install(
        project, repository, state.source, "codex", state.reader, **kw
    )
    state.uninstall = lambda **kw: state.service.uninstall(
        project, repository, state.source, "codex", **kw
    )
    return state


@pytest.mark.parametrize(
    "source", ["SKILL.md", "nested/review/SKILL.md", "directory with spaces/SKILL.md"]
)
def test_full_bundle_pinned_private_bytes_modes_and_offline_lifecycle(
    installation_env, monkeypatch, source
):
    e = installation_env
    e.seed(source=source)
    assert e.install().startswith("Installed")
    destination = e.project / ".agents/skills/review"
    for name, (content, executable) in e.revisions["a" * 40].items():
        assert (destination / name).read_bytes() == content
        assert bool((destination / name).stat().st_mode & 0o111) == executable
    assert not (destination / "link").exists()
    assert not (destination / "submodule").exists()
    assert not (destination / "outside.txt").exists()
    manifest = json.loads((e.project / MANIFEST).read_bytes())
    assert manifest["version"] == 1
    assert manifest["installations"][0]["commit_sha"] == "a" * 40
    assert len(manifest["installations"][0]["files"]) == 3
    assert "private-fixture-token" not in (e.project / MANIFEST).read_text()
    previous = (e.project / MANIFEST).read_bytes()
    monkeypatch.setattr(
        runtime, "github_token", lambda: pytest.fail("Offline operation resolved credentials")
    )
    assert "unchanged" in e.install()
    assert (e.project / MANIFEST).read_bytes() == previous
    assert e.service.list(e.project)[0].state == "current"
    e.catalog.remove_repository(e.skill.repository)
    assert e.service.list(e.project)[0].state == "source unavailable"
    assert e.uninstall().startswith("Uninstalled")
    assert not destination.exists()
    assert e.service.list(e.project) == ()


@pytest.mark.parametrize(
    "outside_path",
    ["docs/2024-01-01T10:00.md", "nested/reviewer/bad?.txt", "unrelated\\file", "trailing. "],
)
def test_nested_bundle_ignores_unsupported_paths_outside_its_directory(
    installation_env, outside_path
):
    e = installation_env
    e.outside_paths = [outside_path]
    e.install()
    target = e.project / ".agents/skills/review"
    assert {p.relative_to(target).as_posix() for p in target.rglob("*") if p.is_file()} == set(
        e.revisions["a" * 40]
    )
    assert len([r for r in e.requests if "/git/blobs/" in r.url.path]) == 3


@pytest.mark.parametrize(
    "path",
    [
        "../escape.txt",
        "docs/../escape.txt",
        "./alias.txt",
        "docs//alias.txt",
        "/absolute.txt",
        "bad?.txt",
    ],
)
def test_bundle_paths_are_validated_without_normalization_before_blob_reads(installation_env, path):
    e = installation_env
    content = b"Unsupported bundle file"
    e.revisions["a" * 40][path] = (content, False)
    with pytest.raises(InstallationError, match="Unsafe relative path"):
        e.install()
    sha = hashlib.sha1(content).hexdigest()
    assert not any(r.url.path.endswith("/git/blobs/" + sha) for r in e.requests)
    assert not (e.project / ".agents").exists()
    assert e.service.list(e.project) == ()


def test_update_uses_latest_scan_and_replaces_added_removed_files(installation_env):
    e = installation_env
    e.install()
    e.seed("b" * 40)
    assert e.service.list(e.project)[0].state == "update available"
    with pytest.raises(InstallationError, match="Use update"):
        e.install()
    assert e.install(update=True).startswith("Updated")
    root = e.project / ".agents/skills/review"
    assert not (root / "scripts").exists()
    assert not (root / "assets").exists()
    assert (root / "new/data.bin").read_bytes() == b"\x00updated\xff"
    assert e.service.list(e.project)[0].installation.commit_sha == "b" * 40
    with pytest.raises(InstallationError, match="changed"):
        e.uninstall(expected_commit="a" * 40)
    assert e.install(update=True).startswith("Already")


@pytest.mark.parametrize(
    "modification", ["edit", "delete", "extra", "directory", "mode", "symlink", "hardlink"]
)
def test_local_changes_refuse_update_and_uninstall_with_exact_paths(installation_env, modification):
    e = installation_env
    e.install()
    root = e.project / ".agents/skills/review"
    path = root / "SKILL.md"
    if modification == "edit":
        path.write_bytes(b"local change")
    elif modification == "delete":
        path.unlink()
    elif modification == "extra":
        path = root / "notes.txt"
        path.write_text("keep me")
    elif modification == "directory":
        path = root / "empty-but-local"
        path.mkdir()
    elif modification == "mode":
        path.chmod(0o755)
    elif modification == "symlink":
        path.unlink()
        path.symlink_to(e.project / "outside")
    else:
        os.link(path, e.project / "outside")
    manifest = (e.project / MANIFEST).read_bytes()
    assert e.service.list(e.project)[0].state == "modified"
    assert str(path.relative_to(e.project)) in e.service.list(e.project)[0].conflicts
    e.seed("b" * 40)
    for operation in (lambda: e.install(update=True), e.uninstall):
        with pytest.raises(InstallationError, match=path.name):
            operation()
    assert (e.project / MANIFEST).read_bytes() == manifest


def test_name_source_agent_and_unowned_path_collisions(installation_env):
    e = installation_env
    e.install()
    original = e.source
    e.seed(source="another/SKILL.md")
    with pytest.raises(InstallationError, match="collision"):
        e.install()
    assert e.install(name="another").startswith("Installed")
    e.service.install(e.project, e.skill.repository, e.source, "claude", e.reader)
    assert len(e.service.list(e.project)) == 3
    with pytest.raises(InstallationError, match="already installed"):
        e.install(name="moved")
    e.source = "new/SKILL.md"
    e.seed(source=e.source)
    target = e.project / ".agents/skills/unowned"
    target.mkdir()
    with pytest.raises(InstallationError, match="collision"):
        e.install(name="unowned")
    assert target.is_dir()
    assert any(r.installation.skill_path == original for r in e.service.list(e.project))


@pytest.mark.parametrize(
    "component", [".agents", ".agents/skills", ".agents/skills/review", ".skill-atlas"]
)
def test_symlink_ancestors_cannot_escape_project(installation_env, tmp_path, component):
    e = installation_env
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep").write_text("untouched")
    path = e.project / component
    path.parent.mkdir(parents=True, exist_ok=True)
    path.symlink_to(outside, target_is_directory=True)
    with pytest.raises(InstallationError):
        e.install()
    assert sorted(p.name for p in outside.iterdir()) == ["keep"]


def test_download_failure_preserves_old_installation(installation_env):
    e = installation_env
    e.install()
    before = (e.project / MANIFEST).read_bytes()
    e.seed("b" * 40)
    e.fail = True
    with pytest.raises(Exception, match="GitHub request failed"):
        e.install(update=True)
    assert (e.project / MANIFEST).read_bytes() == before
    assert (e.project / ".agents/skills/review/scripts/run.sh").exists()


@pytest.mark.parametrize("step", ["stage", "backup", "publish", "manifest"])
@pytest.mark.parametrize("interrupted", [False, True])
def test_failed_and_interrupted_writes_recover_original_files_and_manifest(
    installation_env, monkeypatch, step, interrupted
):
    e = installation_env
    e.install()
    before = (e.project / MANIFEST).read_bytes()
    e.seed("b" * 40)
    real_write = ProjectFiles.write
    real_rename = ProjectFiles.rename
    triggered = False

    def crash():
        nonlocal triggered
        triggered = True
        if interrupted:
            raise KeyboardInterrupt()
        raise OSError("disk full")

    def write(self, path, *args, **kwargs):
        if not triggered and (
            (step == "stage" and path.startswith(STAGE))
            or (step == "manifest" and path == MANIFEST)
        ):
            crash()
        return real_write(self, path, *args, **kwargs)

    def rename(self, source, destination):
        real_rename(self, source, destination)
        if not triggered and (
            (step == "backup" and destination == BACKUP) or (step == "publish" and source == STAGE)
        ):
            crash()

    monkeypatch.setattr(ProjectFiles, "write", write)
    monkeypatch.setattr(ProjectFiles, "rename", rename)
    with pytest.raises(KeyboardInterrupt if interrupted else InstallationError):
        e.install(update=True)
    assert triggered
    assert (e.project / MANIFEST).read_bytes() == before
    assert (e.project / ".agents/skills/review/scripts/run.sh").exists()
    assert not (e.project / ".skill-atlas/transaction").exists()
    assert e.install(update=True).startswith("Updated")


@pytest.mark.parametrize("committed", [False, True])
def test_next_process_recovers_abrupt_stop_at_manifest_boundary(
    installation_env, monkeypatch, committed
):
    e = installation_env
    e.install()
    e.seed("b" * 40)
    write = ProjectRecords.write

    def crash(self, records):
        if committed:
            write(self, records)
        raise KeyboardInterrupt()

    with monkeypatch.context() as patch:
        patch.setattr(ProjectRecords, "write", crash)
        patch.setattr(ProjectTransaction, "recover", lambda self: None)  # Model an abrupt stop.
        with pytest.raises(KeyboardInterrupt):
            e.install(update=True)
    assert (e.project / JOURNAL).exists()
    result = runtime.create_installations(e.settings).list(e.project)
    assert result[0].installation.commit_sha == ("b" if committed else "a") * 40
    assert not result[0].conflicts
    assert not (e.project / JOURNAL).exists()


def test_interruption_recovery_preserves_new_local_edits(installation_env, monkeypatch):
    e = installation_env
    e.install()
    e.seed("b" * 40)
    with monkeypatch.context() as patch:
        patch.setattr(
            ProjectRecords, "write", lambda *args: (_ for _ in ()).throw(KeyboardInterrupt())
        )
        patch.setattr(ProjectTransaction, "recover", lambda self: None)
        with pytest.raises(KeyboardInterrupt):
            e.install(update=True)
    target = e.project / ".agents/skills/review/new/data.bin"
    target.write_bytes(b"new user edits")
    with pytest.raises(InstallationError, match="new/data.bin"):
        e.service.list(e.project)
    assert target.read_bytes() == b"new user edits"
    assert (e.project / BACKUP / "SKILL.md").exists()


def test_concurrent_installs_are_serialized_and_idempotent(installation_env):
    e = installation_env
    barrier = Barrier(4)

    def install(_):
        barrier.wait()
        return e.install()

    with ThreadPoolExecutor(4) as pool:
        results = list(pool.map(install, range(4)))
    assert sum(r.startswith("Installed:") for r in results) == 1
    assert sum(r.startswith("Already") for r in results) == 3
    assert len(e.service.list(e.project)) == 1
    assert len([r for r in e.requests if "/commits/" in r.url.path]) == 1


def test_cli_project_resolution_and_web_parity(installation_env, monkeypatch):
    e = installation_env
    monkeypatch.chdir(e.project)
    runner = CliRunner()
    args = [e.skill.repository.url, e.source, "--agent", "codex"]
    result = runner.invoke(create_app(), ["install", *args])
    assert result.exit_code == 1 and "--project" in result.output
    subprocess.run(["git", "init", "--quiet", "--template=", str(e.project)], check=True)
    nested = e.project / "subdir"
    nested.mkdir()
    monkeypatch.chdir(nested)
    result = runner.invoke(create_app(), ["install", *args])
    assert result.exit_code == 0, result.output
    assert str(e.project / ".agents/skills/review") in result.output
    assert not (nested / ".agents").exists()
    payload = json.loads(runner.invoke(create_app(), ["installed", "--json"]).stdout)
    assert payload[0]["state"] == "current"
    e.seed("b" * 40)
    result = runner.invoke(create_app(), ["update", *args, "--project", str(e.project)])
    assert result.exit_code == 0, result.output
    with TestClient(runtime.create_web_app(e.settings), base_url="http://127.0.0.1") as client:
        response = client.post(
            "/installations/register", data={"project": str(e.project)}, headers=HEADERS
        )
        assert response.status_code == 200, response.text
        page = client.get("/installations", params={"project": str(e.project)})
        assert "current" in page.text and "b" * 40 in page.text
        fields = dict(
            project=str(e.project),
            repository_url=e.skill.repository.url,
            skill_path=e.source,
            agent="codex",
            commit_sha="b" * 40,
        )
        assert (
            client.post("/installations/uninstall", data=fields, headers=HEADERS).status_code == 200
        )
    result = runner.invoke(create_app(), ["status", "--project", str(e.project)])
    assert result.exit_code == 0 and "No skills installed" in result.output


def test_web_registration_preview_stale_selection_and_request_protection(installation_env):
    e = installation_env
    fields = dict(
        project=str(e.project),
        repository_url=e.skill.repository.url,
        skill_path=e.source,
        agent="codex",
        commit_sha="a" * 40,
        destination=str(e.project / ".agents/skills/review"),
    )
    with TestClient(runtime.create_web_app(e.settings), base_url="http://127.0.0.1") as client:
        assert (
            client.post("/installations/install", data=fields, headers=HEADERS).status_code == 409
        )
        for headers in (
            {},
            {**HEADERS, "Origin": "https://evil.invalid"},
            {"Origin": HEADERS["Origin"]},
        ):
            assert (
                client.post(
                    "/installations/register", data={"project": str(e.project)}, headers=headers
                ).status_code
                == 403
            )
        assert not (e.project / ".skill-atlas").exists()
        assert (
            client.post(
                "/installations/register", data={"project": "."}, headers=HEADERS
            ).status_code
            == 409
        )
        assert (
            client.post(
                "/installations/register", data={"project": str(e.project)}, headers=HEADERS
            ).status_code
            == 200
        )
        page = client.get(
            "/installations",
            params={"project": str(e.project), "source": e.skill.repository.url + "|" + e.source},
        )
        assert str(e.project / ".agents/skills/review") in page.text
        assert not e.requests
        e.seed("b" * 40)
        stale = client.post("/installations/install", data=fields, headers=HEADERS)
        assert stale.status_code == 409 and stale.json()["code"] == "stale_selection"
        fields["commit_sha"] = "b" * 40
        wrong = client.post(
            "/installations/install", data={**fields, "destination": "/wrong"}, headers=HEADERS
        )
        assert wrong.status_code == 409
        assert not e.requests
        assert (
            client.post("/installations/install", data=fields, headers=HEADERS).status_code == 200
        )
        (e.project / ".agents/skills/review/local.txt").write_text("keep")
        conflict = client.post("/installations/uninstall", data=fields, headers=HEADERS)
        assert conflict.status_code == 409 and "local.txt" in conflict.text
        e.catalog.remove_repository(e.skill.repository)
        assert client.post("/installations/update", data=fields, headers=HEADERS).status_code == 404
        (e.project / ".agents/skills/review/local.txt").unlink()
        assert (
            client.post("/installations/uninstall", data=fields, headers=HEADERS).status_code == 200
        )


def test_malformed_manifest_and_project_inputs_fail_without_deletion(installation_env):
    e = installation_env
    e.install()
    (e.project / MANIFEST).write_text('{"version": 99, "installations": []}')
    with pytest.raises(InstallationError, match="unsupported"):
        e.uninstall()
    assert (e.project / ".agents/skills/review/SKILL.md").exists()
    for value in (e.project / "missing", e.project / MANIFEST):
        with pytest.raises(InstallationError):
            project_path(value)
    with pytest.raises(InstallationError):
        project_path("relative", web=True)


@pytest.mark.parametrize("operation", ["install", "uninstall"])
@pytest.mark.parametrize("committed", [False, True])
def test_recover_install_and_uninstall_after_abrupt_stop(
    installation_env, monkeypatch, operation, committed
):
    e = installation_env
    if operation == "uninstall":
        e.install()
    write = ProjectRecords.write

    def crash(self, records):
        if committed:
            write(self, records)
        raise KeyboardInterrupt()

    with monkeypatch.context() as patch:
        patch.setattr(ProjectRecords, "write", crash)
        patch.setattr(ProjectTransaction, "recover", lambda self: None)
        with pytest.raises(KeyboardInterrupt):
            e.install() if operation == "install" else e.uninstall()
    statuses = e.service.list(e.project)
    should_exist = committed if operation == "install" else not committed
    assert bool(statuses) == should_exist
    assert (e.project / ".agents/skills/review/SKILL.md").exists() == should_exist
    if statuses:
        assert not statuses[0].conflicts


def test_unrecognized_recovery_files_are_never_deleted(installation_env):
    e = installation_env
    staging = e.project / ".skill-atlas/transaction"
    staging.mkdir(parents=True)
    (staging / "local-notes").write_text("Preserve")
    with pytest.raises(InstallationError, match="Unrecognized"):
        e.install()
    assert (staging / "local-notes").read_text() == "Preserve"


def test_separate_processes_share_one_installation_lock(installation_env):
    import sys

    e = installation_env
    script = """
import sys
from pathlib import Path
from skill_atlas import runtime
from skill_atlas.config import Settings
from skill_atlas.installation import BundleFile
from skill_atlas.models import Repository
class Reader:
    def read_bundle(self, skill):
        return (BundleFile("SKILL.md", b"fixture data"),)
service = runtime.create_installations(Settings(Path(sys.argv[1])))
print(service.install(Path(sys.argv[2]), Repository("acme", "private-skills"),
                      "nested/review/SKILL.md", "codex", Reader()))
"""
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", script, str(e.settings.database_path), str(e.project)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(4)
    ]
    try:
        outputs = [p.communicate(timeout=15) for p in processes]
        assert [p.returncode for p in processes] == [0] * 4, outputs
        assert sum(out.startswith("Installed:") for out, _ in outputs) == 1
        assert sum(out.startswith("Already installed") for out, _ in outputs) == 3
        assert len(e.service.list(e.project)) == 1
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.communicate()


def test_cli_conflicts_missing_source_and_offline_uninstall(installation_env):
    e = installation_env
    runner = CliRunner()
    common = ["--project", str(e.project)]
    args = [e.skill.repository.url, e.source, "--agent", "codex", *common]
    assert runner.invoke(create_app(), ["update", *args]).exit_code == 1
    e.install()
    local = e.project / ".agents/skills/review/local.txt"
    local.write_text("save")
    result = runner.invoke(create_app(), ["installed", *common])
    assert result.exit_code == 0 and "modified" in result.output and "local.txt" in result.output
    assert runner.invoke(create_app(), ["uninstall", *args]).exit_code == 1
    local.unlink()
    e.catalog.remove_repository(e.skill.repository)
    assert runner.invoke(create_app(), ["uninstall", *args]).exit_code == 0
    assert (
        runner.invoke(
            create_app(), ["installed", "--project", str(e.project / "missing")]
        ).exit_code
        == 1
    )


def test_web_malformed_requests_and_upstream_errors(installation_env):
    e = installation_env
    with TestClient(runtime.create_web_app(e.settings), base_url="http://127.0.0.1") as client:
        assert (
            client.post(
                "/installations/register", data={"project": str(e.project)}, headers=HEADERS
            ).status_code
            == 200
        )
        fields = dict(
            project=str(e.project),
            repository_url=e.skill.repository.url,
            skill_path=e.source,
            agent="codex",
            commit_sha="a" * 40,
            destination=str(e.project / ".agents/skills/review"),
        )
        for key in ("commit_sha", "destination"):
            missing = {k: v for k, v in fields.items() if k != key}
            assert (
                client.post("/installations/install", data=missing, headers=HEADERS).status_code
                == 409
            )
        assert (
            client.post("/installations/unknown", data=fields, headers=HEADERS).status_code == 400
        )
        assert (
            client.post(
                "/installations/install", content="x=" + "a" * 8192, headers=HEADERS
            ).status_code
            == 400
        )
        assert (
            client.post(
                "/installations/install", content="project=one&project=two", headers=HEADERS
            ).status_code
            == 400
        )
        e.fail = True
        assert (
            client.post("/installations/install", data=fields, headers=HEADERS).status_code == 502
        )
        page = client.get(
            "/installations", params={"project": str(e.project), "source": "malformed"}
        )
        assert page.status_code == 409
        e.catalog.remove_repository(e.skill.repository)
        page = client.get(
            "/installations",
            params={"project": str(e.project), "source": e.skill.repository.url + "|" + e.source},
        )
        assert page.status_code == 409 and "no longer in the catalog" in page.text


def test_cleanup_interruption_can_resume_without_losing_the_journal(installation_env, monkeypatch):
    e = installation_env
    e.install()
    e.seed("b" * 40)
    remove = ProjectFiles.remove

    def interrupted(self, path):
        remove(self, path)
        if path == BACKUP + "/SKILL.md":
            raise KeyboardInterrupt()

    with monkeypatch.context() as patch:
        patch.setattr(ProjectFiles, "remove", interrupted)
        with pytest.raises(KeyboardInterrupt):
            e.install(update=True)
    assert (e.project / JOURNAL).exists()
    status = e.service.list(e.project)[0]
    assert status.installation.commit_sha == "b" * 40 and not status.conflicts
    assert not (e.project / JOURNAL).exists()


def test_uninstall_recovery_preserves_unexpected_staged_files(installation_env, monkeypatch):
    e = installation_env
    e.install()
    write = ProjectRecords.write

    def stopped(self, records):
        write(self, records)
        raise KeyboardInterrupt()

    with monkeypatch.context() as patch:
        patch.setattr(ProjectRecords, "write", stopped)
        patch.setattr(ProjectTransaction, "recover", lambda self: None)
        with pytest.raises(KeyboardInterrupt):
            e.uninstall()
    unexpected = e.project / STAGE / "local.txt"
    unexpected.parent.mkdir()
    unexpected.write_text("preserve")
    with pytest.raises(InstallationError, match="Unexpected recovery bundle"):
        e.service.list(e.project)
    assert unexpected.read_text() == "preserve"
