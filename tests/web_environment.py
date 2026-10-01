"""Real Web composition with controlled GitHub I/O for pytest and Playwright Test."""

from contextlib import contextmanager
from unittest.mock import patch


@contextmanager
def create_web_environment(tmp_path, scan_result, *, gate_timeout=10):
    """Real Web composition; only GitHub and credential lookup are substituted."""
    import base64
    from threading import Event
    from types import SimpleNamespace

    import httpx

    from skill_atlas import runtime
    from skill_atlas.adapters.storage.sqlite import SQLiteCatalog
    from skill_atlas.config import Settings

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
        listing_gate=Event(),
        # Organization listings name repositories under the requested owner.
        organization=["skills"],
        failed_repositories=set(),
    )
    state.scan_gate.set()
    state.document_gate.set()
    state.listing_gate.set()

    def organization_listing(request):
        import json

        login = json.loads(request.content)["variables"]["login"]
        nodes = [
            {
                "nameWithOwner": f"{login}/{name}",
                "isFork": False,
                "isArchived": False,
                "isEmpty": False,
                "defaultBranchRef": {"target": {"oid": state.commit, "tree": {"oid": "b" * 40}}},
            }
            for name in state.organization
        ]
        owner = {
            "__typename": "Organization",
            "login": login,
            "repositories": {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": nodes},
        }
        return httpx.Response(200, json={"data": {"repositoryOwner": owner}})

    def handler(request):
        state.requests.append(request)
        assert request.headers["Authorization"] == "Bearer fixture-token"
        path = request.url.path
        if path == "/graphql":
            assert state.listing_gate.wait(gate_timeout), "Listing gate was not released"
            return organization_listing(request)
        if "/contents/" in path:
            assert state.document_gate.wait(gate_timeout), "Document gate was not released"
            return httpx.Response(state.document_status, text=state.source)
        assert state.scan_gate.wait(gate_timeout), "Scan gate was not released"
        if state.scan_status != 200:
            return httpx.Response(state.scan_status)
        repository = "/".join(path.strip("/").split("/")[1:3]).lower()
        if repository in {name.lower() for name in state.failed_repositories}:
            return httpx.Response(503)
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
    state.settings = Settings(tmp_path / "catalog.sqlite3")
    state.catalog = SQLiteCatalog(state.settings.database_path)
    with (
        patch.object(runtime, "github_token", lambda: "fixture-token"),
        patch.object(
            runtime.httpx,
            "Client",
            lambda **kwargs: client_type(**kwargs, transport=httpx.MockTransport(handler)),
        ),
    ):
        state.app = runtime.create_web_app(state.settings)
        try:
            yield state
        finally:
            state.scan_gate.set()
            state.document_gate.set()
