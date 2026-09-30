import sqlite3
from dataclasses import replace
from threading import Event, Thread
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient

from skill_atlas.application.similarity import SimilarSkills
from skill_atlas.models import ScanResult


@pytest.fixture
def client(web_environment):
    with TestClient(web_environment.app, base_url="http://127.0.0.1") as client:
        yield client


def selection(skill):
    return {"repository_url": skill.repository.url, "skill_path": skill.path}


@pytest.mark.parametrize("route", ["/similar", "/fragments/similar"])
def test_catalog_query_is_return_context_only(route, client, web_environment, similar_catalog):
    fixture = similar_catalog
    query = "unmatched & <query> #?"
    response = client.get(route, params={**selection(fixture.source), "q": query})
    assert response.status_code == 200
    assert "patch-audit" in response.text
    assert "Same metadata · 3 locations" in response.text
    assert urlencode({"q": query}) in response.text
    assert query not in response.text
    assert 'id="skill-filter"' not in response.text
    assert not web_environment.requests


@pytest.mark.parametrize("route", ["/similar", "/fragments/similar"])
def test_catalog_similarity_is_read_only_and_does_not_fetch_documents(
    route, client, web_environment, similar_catalog
):
    state, fixture = web_environment, similar_catalog
    before = state.settings.database_path.read_bytes()
    response = client.get(route, params=selection(fixture.source))
    assert response.status_code == 200
    assert 'aria-valuetext="100% similarity"' in response.text
    assert 'aria-valuetext="80% similarity"' in response.text
    assert 'min="0" max="100"' in response.text
    assert response.text.count(fixture.source.description) == 2
    assert response.text.count('class="skill-description"') == 2
    assert response.text.count('class="description-toggle"') == 2
    assert "Same metadata · 3 locations" in response.text
    assert "Shared terms:" not in response.text
    for removed in ("Other repositories only", "Apply filter", "Refresh results"):
        assert removed not in response.text
    assert "selected_path=review+%23%3F%2FSKILL.md" in response.text
    assert "fixture-token" not in response.text
    assert response.headers["Cache-Control"] == "no-store"
    assert state.settings.database_path.read_bytes() == before
    assert not state.requests
    assert len(state.catalog.skills()) == 6
    legacy = client.get(route, params={**selection(fixture.source), "other_repositories": True})
    assert legacy.text == response.text  # Retired filters no longer change the search scope.
    assert "other_repositories" not in response.text
    assert ".agents/skills/review/SKILL.md" in response.text
    selected = client.get(
        route,
        params={
            **selection(fixture.source),
            "selected_repository": fixture.remote.repository.url,
            "selected_path": fixture.remote.path,
        },
    )
    assert 'aria-current="true"' in selected.text
    assert f"commit_sha={fixture.remote.commit_sha}" in selected.text
    assert 'hx-trigger="load"' in selected.text
    assert not state.requests


def test_similarity_uses_current_shared_scan_writes_and_clears_removed_selection(
    client, web_environment, similar_catalog
):
    fixture = similar_catalog
    catalog = web_environment.catalog
    params = {
        **selection(fixture.source),
        "selected_repository": fixture.remote.repository.url,
        "selected_path": fixture.remote.path,
    }
    catalog.replace_repository(ScanResult(fixture.remote.repository, "c" * 40, ()))
    response = client.get("/similar", params=params)
    assert response.status_code == 200 and 'data-selected-path=""' in response.text
    assert "other/skills" not in response.text
    catalog.replace_repository(ScanResult(fixture.source.repository, "d" * 40, ()))
    response = client.get("/similar", params=params)
    assert response.status_code == 404 and "missing_similarity_source" in response.text


def test_similarity_empty_missing_and_invalid_catalog_requests(
    client, web_environment, scan_result
):
    params = selection(scan_result.skills[0])
    assert client.get("/similar", params=params).status_code == 404
    assert not web_environment.settings.database_path.exists()
    web_environment.catalog.replace_repository(
        replace(scan_result, skills=(scan_result.skills[0],))
    )
    response = client.get("/similar", params=params)
    assert "No similar skills found" in response.text
    for invalid in (
        {},
        {**params, "repository_url": "bad"},
    ):
        assert client.get("/similar", params=invalid).status_code == 400
    assert (
        client.get("/similar", params={**params, "selected_repository": "bad"}).status_code == 400
    )
    with sqlite3.connect(web_environment.settings.database_path) as connection:
        connection.execute("PRAGMA user_version = 99")
    assert client.get("/similar", params=params).status_code == 500
    with sqlite3.connect(web_environment.settings.database_path) as connection:
        connection.execute("PRAGMA user_version = 0")
    assert client.get("/similar", params=params).status_code == 500
    web_environment.settings.database_path.write_bytes(b"corrupt")
    response = client.get("/similar", params=params)
    assert response.status_code == 500 and "No similar skills found" not in response.text


def test_similarity_metadata_is_escaped(client, web_environment, scan_result):
    source = replace(
        scan_result.skills[0], name="<script>evil()</script>", description="<img src=x>"
    )
    copy = replace(source, path='"><script>bad()</script>/SKILL.md')
    web_environment.catalog.replace_repository(replace(scan_result, skills=(source, copy)))
    response = client.get("/similar", params=selection(source))
    assert response.status_code == 200
    assert "&lt;script&gt;evil()&lt;/script&gt;" in response.text
    assert "<img src=x>" not in response.text and "<script>bad()" not in response.text
    assert "&lt;img src=x&gt;" in response.text
    assert not web_environment.requests


def test_similarity_read_sees_complete_snapshot_during_replacement(web_environment, scan_result):
    catalog = web_environment.catalog
    source = scan_result.skills[0]
    catalog.replace_repository(replace(scan_result, skills=(source, replace(source, path="copy"))))
    deleted, release = Event(), Event()
    failures = []

    def writer():
        try:
            with sqlite3.connect(web_environment.settings.database_path) as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute("DELETE FROM skills")
                deleted.set()
                assert release.wait(5)
        except BaseException as exc:
            failures.append(exc)

    thread = Thread(target=writer)
    thread.start()
    try:
        assert deleted.wait(5)
        result = SimilarSkills(catalog).search(source.repository, source.path)
        assert result.source == source
        assert result.matches[0].display_score == 100
        assert result.matches[0].skill.path == "copy"
    finally:
        release.set()
        thread.join(5)
    assert not thread.is_alive() and not failures
    assert catalog.skills() == ()
