import json
import re
from dataclasses import replace
from html import unescape

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from skill_atlas import runtime
from skill_atlas.cli.app import create_app
from skill_atlas.models import Repository

HEADERS = {"Origin": "http://127.0.0.1", "X-Atlas-Request": "1", "HX-Request": "true"}
ACME = "https://github.com/acme/skills"
OTHER = Repository("other", "repo")


@pytest.fixture
def client(web_environment):
    with TestClient(web_environment.app, base_url="http://127.0.0.1") as client:
        yield client


@pytest.fixture
def catalog(web_environment, scan_result):
    web_environment.catalog.replace_repository(scan_result)
    web_environment.catalog.replace_repository(replace(scan_result, repository=OTHER))
    return web_environment.catalog


def star(client, path="review/SKILL.md", starred="1", repository=ACME, headers=HEADERS):
    return client.post(
        "/stars",
        data={"repository_url": repository, "skill_path": path, "starred": starred},
        headers=headers,
    )


def starred(catalog):
    return [(skill.repository.url, skill.path) for skill in catalog.skills() if skill.starred]


def toggles(html):
    return {
        (unescape(repository), unescape(path)): pressed
        for pressed, repository, path in re.findall(
            r'class="star-toggle" aria-pressed="(true|false)" '
            r'data-star-repository="([^"]*)" data-star-path="([^"]*)"',
            html,
        )
    }


def test_star_toggle_is_idempotent_persistent_and_shared_with_the_cli(
    client, web_environment, catalog
):
    for _ in range(2):
        response = star(client)
        assert response.status_code == 200, response.text
        assert toggles(response.text) == {(ACME, "review/SKILL.md"): "true"}
        assert "Star code-review" in response.text
    assert starred(catalog) == [(ACME, "review/SKILL.md")]
    page = client.get("/repository", params={"repository_url": ACME})
    assert toggles(page.text) == {
        (ACME, "review/SKILL.md"): "true",
        (ACME, "release notes/SKILL.md"): "false",
    }

    # A restarted server reads the same stars, and CLI changes appear without a rescan.
    runner = CliRunner()
    result = runner.invoke(create_app(), ["star", OTHER.url, "release notes/SKILL.md"])
    assert result.exit_code == 0, result.output
    with TestClient(
        runtime.create_web_app(web_environment.settings), base_url="http://127.0.0.1"
    ) as restarted:
        listing = restarted.get(
            "/fragments/repository-skills", params={"repository_url": OTHER.url}
        )
        assert toggles(listing.text)[(OTHER.url, "release notes/SKILL.md")] == "true"
        for _ in range(2):
            assert star(restarted, starred="0").status_code == 200
    assert starred(catalog) == [(OTHER.url, "release notes/SKILL.md")]
    payload = json.loads(runner.invoke(create_app(), ["filter", "--starred", "--json"]).stdout)
    assert [skill["skill_path"] for skill in payload["skills"]] == ["release notes/SKILL.md"]
    assert not web_environment.requests
    assert 'class="job"' not in client.get("/").text  # No scan was started.


def test_open_document_header_reflects_and_toggles_the_same_identity(
    client, web_environment, catalog, scan_result
):
    skill = scan_result.skills[0]
    catalog.set_starred(skill.repository, skill.path, True)
    params = {"repository_url": ACME, "skill_path": skill.path, "commit_sha": skill.commit_sha}
    document = client.get("/fragments/document", params=params)
    assert document.status_code == 200
    header = document.text.split('class="document-toolbar"', 1)[1].split("</div></div>", 1)[0]
    assert toggles(header) == {(ACME, skill.path): "true"}
    assert len(web_environment.requests) == 1  # Starring never adds GitHub reads.
    assert star(client, starred="0").status_code == 200
    assert len(web_environment.requests) == 1


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {**HEADERS, "Origin": "http://evil.test"},
        {"X-Atlas-Request": "1"},
        {**HEADERS, "X-Atlas-Request": ""},
        {**HEADERS, "Host": "evil.test"},
    ],
    ids=["no-headers", "foreign-origin", "no-origin", "no-request-header", "foreign-host"],
)
def test_cross_origin_star_requests_are_rejected_without_writes(client, catalog, headers):
    before = catalog.path.read_bytes()
    response = star(client, headers=headers)
    assert response.status_code in (400, 403)
    assert catalog.path.read_bytes() == before and starred(catalog) == []


@pytest.mark.parametrize(
    ("data", "status", "code"),
    [
        (
            {"repository_url": "bad", "skill_path": "review/SKILL.md", "starred": "1"},
            400,
            "invalid_input",
        ),
        ({"repository_url": ACME, "starred": "1"}, 400, "invalid_input"),
        (
            {"repository_url": ACME, "skill_path": "review/SKILL.md", "starred": "on"},
            400,
            "invalid_input",
        ),
        ({"repository_url": ACME, "skill_path": "review/SKILL.md"}, 400, "invalid_input"),
        (
            {"repository_url": ACME, "skill_path": "missing/SKILL.md", "starred": "1"},
            404,
            "missing_skill",
        ),
    ],
)
def test_invalid_and_missing_star_requests_report_errors(client, catalog, data, status, code):
    before = catalog.path.read_bytes()
    response = client.post("/stars", data=data, headers=HEADERS)
    assert response.status_code == status
    assert f'data-error-code="{code}"' in response.text
    assert response.headers["X-Error-Code"] == code
    assert catalog.path.read_bytes() == before


def test_oversized_bodies_and_missing_catalogs_are_not_written(client, web_environment):
    assert client.post("/stars", content=b"x" * 8193, headers=HEADERS).status_code == 400
    response = star(client)
    assert response.status_code == 404 and "Skill not found in the catalog" in response.text
    assert not web_environment.settings.database_path.exists()


@pytest.mark.parametrize(
    "route",
    [
        "/",
        "/fragments/repositories",
        "/repository",
        "/fragments/repository",
        "/fragments/skills",
        "/fragments/repository-skills",
    ],
)
def test_starred_only_url_state_restricts_every_catalog_route(
    client, web_environment, catalog, route
):
    catalog.set_starred(OTHER, "review/SKILL.md", True)
    before = catalog.path.read_bytes()
    params = {"repository_url": OTHER.url, "starred": "1"}
    response = client.get(route, params=params)
    assert response.status_code == 200, response.text
    assert toggles(response.text) == {(OTHER.url, "review/SKILL.md"): "true"}
    assert "release-notes" not in response.text
    links = re.findall(r'class="(?:catalog-skill|skill-link)" href="([^"]*)"', response.text)
    assert links and all("starred=1" in unescape(link) for link in links)
    if route in ("/", "/repository", "/fragments/repository"):
        assert re.search(
            r'id="starred-filter" type="checkbox" name="starred" value="1" checked', response.text
        )
        assert "filter-controls is-open" in response.text
    if route in ("/", "/fragments/repositories"):
        assert "1 matching starred skill across 1 repository" in response.text
        assert "1 of 2 skills" in response.text and "Acme/skills" not in response.text
    if route in ("/repository", "/fragments/repository", "/fragments/skills"):
        assert 'data-skill-count="1 of 2 skills"' in response.text
    unfiltered = client.get(route, params={"repository_url": OTHER.url})
    assert 'name="starred" value="1" checked' not in unfiltered.text
    assert catalog.path.read_bytes() == before
    assert not web_environment.requests


def test_starred_only_empty_states_offer_recovery(client, catalog, scan_result):
    home = client.get("/", params={"starred": "1"}).text
    assert "No starred skills." in home and "Star a skill to find it here." in home
    assert "data-clear-starred" in home and "data-clear-filter>Clear filter" not in home
    dialog = re.search(r"<dialog\b[^>]*>", home)
    assert dialog is not None and " open" not in dialog[0]
    assert home.count("data-open-scan") == 1  # No empty-catalog scan prompt.
    both = client.get("/fragments/repositories", params={"starred": "1", "q": "notes"}).text
    assert "No starred skills match “notes”." in both
    assert "data-clear-filter>Clear filter" in both and "data-clear-starred" in both
    detail = client.get(
        "/repository",
        params={"repository_url": ACME, "starred": "1", "skill_path": "review/SKILL.md"},
    ).text
    assert "No starred skills." in detail
    assert 'class="filter-notice" >The open skill is hidden' in detail
    assert 'href="/?q=&amp;starred=1">← All repositories' in detail
    expanded = client.get(
        "/fragments/repository-skills", params={"repository_url": ACME, "starred": "1"}
    ).text
    assert "No starred skills." in expanded


def test_pre_star_catalogs_are_browsable_and_upgrade_on_first_star(
    client, web_environment, scan_result
):
    import sqlite3

    from skill_atlas.adapters.storage import migrations

    path = web_environment.settings.database_path
    with sqlite3.connect(path) as connection:
        for statement in migrations.MIGRATIONS[0].statements:
            connection.execute(statement)
        connection.execute("PRAGMA user_version = 1")
        connection.execute(
            "INSERT INTO skills VALUES (?, ?, ?, ?, ?, ?)",
            (ACME, "Acme/skills", "review/SKILL.md", "code-review", "Review.", "a" * 40),
        )
    connection.close()
    before = path.read_bytes()
    page = client.get("/repository", params={"repository_url": ACME})
    assert page.status_code == 200
    assert toggles(page.text) == {(ACME, "review/SKILL.md"): "false"}
    assert "No starred skills." in client.get("/", params={"starred": "1"}).text
    assert path.read_bytes() == before
    assert star(client).status_code == 200
    assert starred(web_environment.catalog) == [(ACME, "review/SKILL.md")]
