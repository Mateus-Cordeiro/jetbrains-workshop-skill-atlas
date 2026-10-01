"""Real Web composition with controlled GitHub I/O for pytest and Playwright Test."""

from contextlib import contextmanager
from unittest.mock import patch


@contextmanager
def create_web_environment(tmp_path, scan_result, *, gate_timeout=10):
    """Real Web composition; only GitHub and credential lookup are substituted."""
    import base64
    import json
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
        grouping_requests=[],
        grouping_status=200,
        grouping_content=None,
        grouping_content_by_perspective={},
        grouping_gate=Event(),
        scan_gate=Event(),
        document_gate=Event(),
    )
    state.scan_gate.set()
    state.document_gate.set()
    state.grouping_gate.set()

    def handler(request):
        if request.url.host == "127.0.0.1":
            assert request.url.path == "/api/chat"
            assert "Authorization" not in request.headers
            state.grouping_requests.append(request)
            assert state.grouping_gate.wait(gate_timeout), "Grouping gate was not released"
            data = json.loads(json.loads(request.content)["messages"][1]["content"])
            prompt = json.loads(request.content)["messages"][0]["content"]
            perspective = "topics" if "subject area" in prompt else "capabilities"
            content = state.grouping_content_by_perspective.get(perspective, state.grouping_content)
            content = (
                content
                if content is not None
                else {
                    "groups": [{"title": "Improve software", "skill_ids": [s["id"] for s in data]}]
                }
            )
            return httpx.Response(
                state.grouping_status,
                json={
                    "done": True,
                    "done_reason": "stop",
                    "message": {"content": json.dumps(content)},
                },
            )
        state.requests.append(request)
        assert request.headers["Authorization"] == "Bearer fixture-token"
        path = request.url.path
        if "/contents/" in path:
            assert state.document_gate.wait(gate_timeout), "Document gate was not released"
            return httpx.Response(state.document_status, text=state.source)
        assert state.scan_gate.wait(gate_timeout), "Scan gate was not released"
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
            state.grouping_gate.set()
