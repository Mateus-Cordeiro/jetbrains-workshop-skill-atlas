import pytest

from skill_atlas.models import Repository, ScanResult, Skill


@pytest.fixture(autouse=True)
def isolated_catalog_and_credentials(tmp_path, monkeypatch):
    """A test must never touch a developer's catalog or use their API tokens."""
    monkeypatch.setenv("SKILL_ATLAS_DB", str(tmp_path / "catalog.sqlite3"))
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)


@pytest.fixture
def repository():
    return Repository("Acme", "skills")


@pytest.fixture
def scan_result(repository):
    return ScanResult(
        repository,
        "a" * 40,
        (
            Skill(
                repository,
                "review/SKILL.md",
                "code-review",
                "Review code changes for correctness and maintainability.",
                "a" * 40,
            ),
            Skill(
                repository,
                "release notes/SKILL.md",
                "release-notes",
                "Draft release notes from a set of changes.",
                "a" * 40,
            ),
        ),
    )


@pytest.fixture
def web_environment(tmp_path, monkeypatch, scan_result):
    """Real Web composition; only GitHub and credential lookup are substituted."""
    import base64
    from threading import Event
    from types import SimpleNamespace

    import httpx

    from skill_atlas import runtime
    from skill_atlas.config import Settings
    from skill_atlas.storage.sqlite import SQLiteCatalog

    state = SimpleNamespace(
        source=(
            "---\nname: code-review\ndescription: Review changes.\n---\n"
            "# Review changes\n\nA useful skill.\n"
        ),
        document_status=200,
        scan_status=200,
        zero=False,
        commit="a" * 40,
        requests=[],
        scan_gate=Event(),
        document_gate=Event(),
    )
    state.scan_gate.set()
    state.document_gate.set()

    def handler(request):
        state.requests.append(request)
        assert request.headers["Authorization"] == "Bearer fixture-token"
        path = request.url.path
        if "/contents/" in path:
            assert state.document_gate.wait(10), "Document gate was not released"
            return httpx.Response(state.document_status, text=state.source)
        assert state.scan_gate.wait(10), "Scan gate was not released"
        if state.scan_status != 200:
            return httpx.Response(state.scan_status)
        if len(path.strip("/").split("/")) == 3:
            data = {"full_name": path.removeprefix("/repos/"), "default_branch": "main"}
        elif "/commits/" in path:
            data = {"sha": state.commit, "commit": {"tree": {"sha": "b" * 40}}}
        elif "/git/trees/" in path:
            data = {
                "truncated": False,
                "tree": []
                if state.zero
                else [
                    {"path": skill.path, "type": "blob", "mode": "100644", "sha": "c" * 40}
                    for skill in scan_result.skills
                ],
            }
        else:
            data = {
                "encoding": "base64",
                "content": base64.b64encode(state.source.encode()).decode(),
            }
        return httpx.Response(200, json=data)

    client_type = httpx.Client
    monkeypatch.setattr(runtime, "github_token", lambda: "fixture-token")
    monkeypatch.setattr(
        runtime.httpx,
        "Client",
        lambda **kwargs: client_type(**kwargs, transport=httpx.MockTransport(handler)),
    )
    state.settings = Settings(tmp_path / "catalog.sqlite3")
    state.catalog = SQLiteCatalog(state.settings.database_path)
    state.app = runtime.create_web_app(state.settings)
    yield state
    state.scan_gate.set()
    state.document_gate.set()
