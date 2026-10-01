import sqlite3
from dataclasses import replace
from re import findall

import pytest
from fastapi.testclient import TestClient

from skill_atlas.adapters.storage.sqlite import SQLiteCatalog
from skill_atlas.models import Repository

HEADERS = {"Origin": "http://127.0.0.1", "X-Atlas-Request": "1", "HX-Request": "true"}


@pytest.fixture
def client(web_environment):
    with TestClient(web_environment.app, base_url="http://127.0.0.1") as client:
        yield client


def remove(client, repository):
    return client.post("/repositories/remove", data={"repository_url": repository}, headers=HEADERS)


def test_remove_is_local_idempotent_and_preserves_other_stars(client, web_environment, scan_result):
    catalog = web_environment.catalog
    catalog.replace_repository(scan_result)
    other = Repository("other", "repo")
    catalog.replace_repository(replace(scan_result, repository=other))
    for repository in (scan_result.repository, other):
        catalog.set_starred(repository, scan_result.skills[0].path, True)
    before = catalog.skills(other)
    for _ in range(2):
        assert remove(client, "https://github.com/ACME/SKILLS.git/").status_code == 204
        assert catalog.skills(scan_result.repository) == ()
        assert catalog.skills(other) == before
    assert SQLiteCatalog(catalog.path).skills() == before
    assert 'data-repository="https://github.com/acme/skills"' not in client.get("/").text
    detail = client.get("/repository", params={"repository_url": scan_result.repository.url})
    assert "No skills found" in detail.text
    missing = client.get(
        "/fragments/document",
        params={
            "repository_url": scan_result.repository.url,
            "skill_path": scan_result.skills[0].path,
            "commit_sha": scan_result.commit_sha,
        },
    )
    assert missing.status_code == 404
    # Later successful scans can add the repository again, with fresh unstarred identities.
    catalog.replace_repository(scan_result)
    assert not any(skill.starred for skill in catalog.skills(scan_result.repository))
    assert web_environment.requests == [] and web_environment.grouping_requests == []


def test_missing_removal_does_not_create_catalog(client, web_environment, scan_result):
    assert remove(client, scan_result.repository.url).status_code == 204
    assert not web_environment.catalog.path.exists()


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Origin": "http://127.0.0.1"},
        {"X-Atlas-Request": "1"},
        {**HEADERS, "Origin": "https://evil.test"},
    ],
)
def test_remove_rejects_cross_origin_requests(client, web_environment, scan_result, headers):
    web_environment.catalog.replace_repository(scan_result)
    response = client.post(
        "/repositories/remove", data={"repository_url": scan_result.repository.url}, headers=headers
    )
    assert response.status_code == 403
    assert web_environment.catalog.skills() == scan_result.skills


@pytest.mark.parametrize(
    "repository_url",
    [
        "",
        "https://github.com/acme",
        "https://evil.test/acme/repo",
        "https://github.com/acme/skills?x=1",
        "x" * 9000,
    ],
    ids=["empty", "organization", "foreign-host", "query", "too-long"],
)
def test_remove_rejects_invalid_input(client, web_environment, scan_result, repository_url):
    web_environment.catalog.replace_repository(scan_result)
    response = remove(client, repository_url)
    assert response.status_code == 400 and response.headers["X-Error-Code"] == "invalid_input"
    assert web_environment.catalog.skills() == scan_result.skills


def test_failed_deletion_rolls_back_and_returns_retryable_error(
    client, web_environment, scan_result
):
    catalog = web_environment.catalog
    catalog.replace_repository(scan_result)
    catalog.set_starred(scan_result.repository, scan_result.skills[0].path, True)
    before = catalog.skills()
    with sqlite3.connect(catalog.path) as connection:
        # Fail after a deletion has begun; the transaction must restore all identities and stars.
        connection.execute(
            "CREATE TRIGGER fail_delete AFTER DELETE ON skills BEGIN "
            "SELECT RAISE(ABORT, 'private failure detail'); END"
        )
    response = remove(client, scan_result.repository.url)
    assert response.status_code == 500
    assert "Could not remove the repository" in response.text
    assert "private failure detail" not in response.text
    assert catalog.skills() == before


def test_remove_rejects_newer_and_corrupt_catalogs(client, web_environment, scan_result):
    catalog = web_environment.catalog
    catalog.replace_repository(scan_result)
    with sqlite3.connect(catalog.path) as connection:
        connection.execute("PRAGMA user_version = 999")
    before = catalog.path.read_bytes()
    assert remove(client, scan_result.repository.url).status_code == 500
    assert catalog.path.read_bytes() == before
    catalog.path.write_bytes(b"corrupt")
    assert remove(client, scan_result.repository.url).status_code == 500
    assert catalog.path.read_bytes() == b"corrupt"


@pytest.mark.parametrize("route", ["/", "/fragments/repositories"])
@pytest.mark.parametrize(
    "sort, names", [("none", ["a", "b", "c"]), ("asc", ["b", "c", "a"]), ("desc", ["a", "b", "c"])]
)
@pytest.mark.parametrize("filtered", [False, True])
def test_sort_uses_total_counts_in_full_pages_and_fragments(
    client, web_environment, scan_result, route, sort, names, filtered
):
    for name, count in (("a", 3), ("b", 1), ("c", 1)):
        repository = Repository("acme", name)
        web_environment.catalog.replace_repository(
            replace(
                scan_result,
                repository=repository,
                skills=tuple(
                    replace(scan_result.skills[0], path=f"{i}/SKILL.md") for i in range(count)
                ),
            )
        )
        web_environment.catalog.set_starred(repository, "0/SKILL.md", True)
    response = client.get(
        route,
        params={"sort": sort, "q": "review" if filtered else "", "starred": str(filtered).lower()},
    )
    assert response.status_code == 200
    assert findall(r'data-repository="https://github.com/acme/([abc])"', response.text) == names
    if filtered:
        assert "3 matching starred skills across 3 repositories" in response.text
    if route == "/":
        assert f'value="{sort}" selected' in response.text
    assert web_environment.requests == []
    assert client.get(route, params={"sort": "invalid"}).status_code == 400
