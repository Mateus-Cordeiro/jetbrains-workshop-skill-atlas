import sqlite3
from dataclasses import replace
from time import monotonic, sleep

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from skill_atlas.cli import create_app
from skill_atlas.commands import serve
from skill_atlas.errors import CatalogError
from skill_atlas.models import Repository
from skill_atlas.storage.sqlite import SQLiteCatalog

HEADERS = {"Origin": "http://127.0.0.1", "X-Atlas-Request": "1", "HX-Request": "true"}


@pytest.fixture
def client(web_environment):
    with TestClient(web_environment.app, base_url="http://127.0.0.1") as client:
        yield client


def submit(client, repository="https://github.com/acme/skills"):
    return client.post("/scans", data={"repository_url": repository}, headers=HEADERS)


def wait_scan(client, response, state="succeeded"):
    assert response.status_code == 202, response.text
    deadline = monotonic() + 5
    while monotonic() < deadline:
        result = client.get(response.headers["Location"])
        if f'data-state="{state}"' in result.text:
            return result
        sleep(0.01)
    pytest.fail(result.text)


def test_catalog_queries_preserve_schema_and_report_failures(tmp_path, scan_result):
    path = tmp_path / "catalog.sqlite3"
    catalog = SQLiteCatalog(path)
    assert catalog.repositories() == ()
    assert catalog.skills(scan_result.repository) == ()
    assert catalog.skill(scan_result.repository, "SKILL.md") is None
    assert not path.exists()
    catalog.replace_repository(scan_result)
    before = path.read_bytes()
    assert catalog.repositories()[0].skill_count == 2
    assert catalog.skills(scan_result.repository) == scan_result.skills
    assert (
        catalog.skill(scan_result.repository, scan_result.skills[0].path) == scan_result.skills[0]
    )
    assert path.read_bytes() == before
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version = 99")
    with pytest.raises(CatalogError, match="newer"):
        catalog.repositories()
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version = 0")
    with pytest.raises(CatalogError, match="Unsupported"):
        catalog.skills(scan_result.repository)
    path.write_bytes(b"corrupt")
    with pytest.raises(CatalogError, match="Could not read"):
        catalog.repositories()


def test_pages_and_packaged_assets(client, web_environment, scan_result):
    assert "No repositories" in client.get("/").text
    assert not web_environment.settings.database_path.exists()
    web_environment.catalog.replace_repository(scan_result)
    home = client.get("/")
    assert "Acme/skills" in home.text and "2 skills" in home.text
    detail = client.get("/repository", params={"repository_url": scan_result.repository.url})
    assert "Select a skill" in detail.text
    assert detail.text.index("code-review") < detail.text.index("release-notes")
    assert not web_environment.requests
    for asset in ("app.css", "app.js", "htmx.min.js", "HTMX-LICENSE.txt"):
        assert client.get(f"/static/{asset}").status_code == 200
    assert "script-src 'self'" in home.headers["Content-Security-Policy"]
    assert home.headers["cache-control"] == "no-store"
    assert "Acme/skills" in client.get("/fragments/repositories").text
    selected = client.get(
        "/fragments/repository",
        params={
            "repository_url": scan_result.repository.url,
            "skill_path": scan_result.skills[0].path,
        },
    )
    assert 'hx-trigger="load"' in selected.text
    assert client.get("/repository").status_code == 400
    assert client.get("/repository", params={"repository_url": "bad"}).status_code == 400
    assert client.get("/", headers={"Host": "evil.test"}).status_code == 400
    assert client.get("/", headers={"Origin": "https://evil.test"}).status_code == 403
    assert client.get("/scans/unknown", headers={"HX-Request": "true"}).status_code == 404


def test_scan_rescan_zero_and_failed_scan_preserve_catalog(client, web_environment, scan_result):
    state = web_environment
    first = submit(client)
    wait_scan(client, first)
    assert len(state.catalog.skills(scan_result.repository)) == 2
    # Same-name skills at different paths remain separate.
    assert len({skill.name for skill in state.catalog.skills(scan_result.repository)}) == 1
    other = Repository("other", "repo")
    state.catalog.replace_repository(replace(scan_result, repository=other))
    before = state.settings.database_path.read_bytes()
    state.scan_status = 404
    failed = wait_scan(client, submit(client), "failed")
    assert "private repository access" in failed.text
    assert state.settings.database_path.read_bytes() == before
    state.scan_status = 200
    state.commit = "d" * 40
    wait_scan(client, submit(client))
    assert state.catalog.skills(scan_result.repository)[0].commit_sha == "d" * 40
    state.zero = True
    empty = wait_scan(client, submit(client))
    assert "No skills found" in empty.text
    assert [r.repository.url for r in state.catalog.repositories()] == [other.url]
    detail = client.get("/repository", params={"repository_url": scan_result.repository.url})
    assert "No skills found" in detail.text
    assert 'id="document"' not in detail.text


def test_scan_validation_and_cross_origin_rejection(client):
    for headers in (
        {},
        {**HEADERS, "Origin": "http://evil.test"},
        {**HEADERS, "X-Atlas-Request": ""},
    ):
        assert (
            client.post(
                "/scans", data={"repository_url": "https://github.com/acme/skills"}, headers=headers
            ).status_code
            == 403
        )
    invalid = submit(client, "https://token:secret@github.com/acme/skills")
    assert invalid.status_code == 400 and "secret" not in invalid.text
    assert client.post("/scans", content=b"x" * 8193, headers=HEADERS).status_code == 400
    assert client.post("/scans", content=b"\xff", headers=HEADERS).status_code == 400


def test_documents_are_pinned_private_and_transient(client, web_environment, scan_result):
    state = web_environment
    skill = replace(scan_result.skills[0], path="nested/a #?/SKILL.md")
    state.catalog.replace_repository(replace(scan_result, skills=(skill,)))
    before = state.settings.database_path.read_bytes()
    state.source += "\n<script>danger()</script>\n"
    params = {
        "repository_url": skill.repository.url,
        "skill_path": skill.path,
        "commit_sha": skill.commit_sha,
    }
    response = client.get("/fragments/document", params=params)
    assert response.status_code == 200
    assert 'id="document-source"' in response.text
    assert "&lt;script&gt;" in response.text and "<script>" not in response.text
    assert "fixture-token" not in response.text
    request = state.requests[-1]
    assert request.url.params["ref"] == skill.commit_sha
    assert request.url.path.endswith(skill.path)
    assert request.headers["Accept"] == "application/vnd.github.raw+json"
    assert response.headers["cache-control"] == "no-store"
    assert state.settings.database_path.read_bytes() == before
    assert list(state.settings.database_path.parent.glob("*")) == [state.settings.database_path]
    assert (
        client.get("/fragments/document", params={**params, "commit_sha": "d" * 40}).status_code
        == 409
    )
    assert (
        client.get("/fragments/document", params={**params, "skill_path": "missing"}).status_code
        == 404
    )
    state.document_status = 403
    failed = client.get("/fragments/document", params=params)
    assert failed.status_code == 502 and "Retry" in failed.text
    assert state.settings.database_path.read_bytes() == before


def test_corrupt_catalog_is_not_an_empty_page(client, web_environment):
    web_environment.settings.database_path.write_text("broken")
    response = client.get("/")
    assert response.status_code == 500
    assert "Could not read" in response.text
    assert "No repositories" not in response.text


def test_serve_command_and_startup_error(monkeypatch):
    calls = []
    monkeypatch.setattr(serve.uvicorn, "run", lambda app, **options: calls.append(options))
    result = CliRunner().invoke(create_app(), ["serve", "--port", "8123"])
    assert result.exit_code == 0
    assert "http://127.0.0.1:8123" in result.stdout
    assert calls == [{"host": "127.0.0.1", "port": 8123}]
    assert CliRunner().invoke(create_app(), ["serve", "--port", "0"]).exit_code == 2

    def failure(*args, **kwargs):
        raise OSError(48, "Address already in use")

    monkeypatch.setattr(serve.uvicorn, "run", failure)
    result = CliRunner().invoke(create_app(), ["serve"])
    assert result.exit_code == 1
    assert "Address already in use" in result.stderr


def test_escaped_metadata_and_queue_capacity(tmp_path, scan_result):
    from contextlib import contextmanager

    from skill_atlas.jobs import ScanJobs
    from skill_atlas.web.app import create_app as web_app

    catalog = SQLiteCatalog(tmp_path / "catalog.sqlite3")
    catalog.replace_repository(
        replace(
            scan_result,
            skills=(
                replace(
                    scan_result.skills[0],
                    name="<script>steal()</script>",
                    description="<img src=x>",
                ),
            ),
        )
    )

    @contextmanager
    def no_documents():
        raise AssertionError("Browsing metadata must not retrieve documents")
        yield

    jobs = ScanJobs(lambda repository: scan_result, capacity=0)
    with TestClient(web_app(catalog, jobs, no_documents), base_url="http://127.0.0.1") as client:
        response = client.get("/repository", params={"repository_url": scan_result.repository.url})
        assert "&lt;script&gt;steal()&lt;/script&gt;" in response.text
        assert "<img src=x>" not in response.text
        full = submit(client)
        assert full.status_code == 503 and "queue_full" in full.text
