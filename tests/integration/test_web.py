from dataclasses import replace
from re import findall
from time import monotonic, sleep

import pytest
from fastapi.testclient import TestClient

from skill_atlas.adapters.storage.sqlite import SQLiteCatalog
from skill_atlas.models import Repository

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
    for asset in ("app.css", "app.js", "filters.js", "scan.js", "htmx.min.js", "HTMX-LICENSE.txt"):
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


def test_catalog_controls_and_commit_metadata(client, web_environment, scan_result):
    empty = client.get("/").text
    assert 'aria-haspopup="dialog" aria-controls="scan-dialog"' in empty
    assert "Scan repository or organization" in empty
    web_environment.catalog.replace_repository(scan_result)
    home = client.get("/").text
    assert '<dialog id="scan-dialog"' in home
    assert '<label for="repository-url">GitHub URL</label>' in home
    assert "https://github.com/organization" in home
    assert 'data-error-target="#scan-dialog-feedback"' in home
    assert "COMMIT" not in home and scan_result.commit_sha[:8] not in home
    assert "Your skill library" not in home
    for skills in (scan_result.skills, ()):
        web_environment.catalog.replace_repository(replace(scan_result, skills=skills))
        for route in ("/repository", "/fragments/repository"):
            detail = client.get(route, params={"repository_url": scan_result.repository.url}).text
            assert 'hx-post="/scans"' not in detail
            assert "Snapshot" not in detail
            assert "Rescan" not in detail
    assert not web_environment.requests


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


@pytest.mark.parametrize(
    "route",
    [
        "/repository",
        "/fragments/repository",
        "/fragments/skills",
        "/fragments/repository-skills",
        "/",
        "/fragments/repositories",
    ],
)
def test_skill_list_keeps_full_escaped_descriptions_without_visible_paths(
    client, web_environment, scan_result, route
):
    description = "Long description. " * 30 + "<script>steal()</script>"
    skill = replace(scan_result.skills[0], description=description)
    web_environment.catalog.replace_repository(replace(scan_result, skills=(skill,)))
    response = client.get(route, params={"repository_url": skill.repository.url, "q": "Long"})
    assert response.status_code == 200
    listing = next(
        nav
        for nav in findall(r"<nav ([\s\S]*?)</nav>", response.text)
        if 'class="skill-description"' in nav
    )
    assert description.replace("<", "&lt;").replace(">", "&gt;") in listing
    assert "skill_path=review%2FSKILL.md" in listing
    assert f"<code>{skill.path}</code>" not in listing
    assert 'aria-expanded="false"' in listing
    controls = findall(r'aria-controls="([^"]+)"', listing)
    assert len(controls) == 1
    assert f'id="{controls[0]}"' in listing
    assert not web_environment.requests


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


@pytest.mark.parametrize("fragment", [False, True], ids=["page", "fragment"])
@pytest.mark.parametrize(
    ("path", "status", "code"),
    [
        ("/repository", 400, "invalid_input"),
        ("/repository?repository_url=bad", 400, "invalid_input"),
        ("/scans/unknown", 404, "missing_job"),
    ],
)
def test_http_errors_preserve_layout_and_response_protections(client, fragment, path, status, code):
    response = client.get(path, headers={"HX-Request": "true"} if fragment else {})
    assert response.status_code == status
    assert response.headers["X-Error-Code"] == code
    assert f'data-error-code="{code}"' in response.text
    assert ("<!doctype html>" in response.text.lower()) is not fragment
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]


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


def test_escaped_metadata_and_queue_capacity(tmp_path, scan_result):
    from contextlib import contextmanager

    from skill_atlas.adapters.storage.grouping import SQLiteGroups
    from skill_atlas.application.grouping import SkillGroups
    from skill_atlas.application.grouping_jobs import GroupingJobs
    from skill_atlas.application.scan_jobs import ScanJobs
    from skill_atlas.application.similarity import SimilarSkills
    from skill_atlas.application.stars import Stars
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

    def no_generation(_):
        raise AssertionError("Browsing metadata must not generate groups")

    with TestClient(
        web_app(
            catalog,
            jobs,
            no_documents,
            SimilarSkills(catalog),
            Stars(catalog),
            SkillGroups(SQLiteGroups(catalog)),
            GroupingJobs(no_generation),
        ),
        base_url="http://127.0.0.1",
    ) as client:
        response = client.get("/repository", params={"repository_url": scan_result.repository.url})
        assert "&lt;script&gt;steal()&lt;/script&gt;" in response.text
        assert "<img src=x>" not in response.text
        full = submit(client)
        assert full.status_code == 503 and "queue_full" in full.text


def test_catalog_filtering_and_expansion_share_matching_without_upstream_reads(
    client, web_environment, scan_result
):
    state = web_environment
    state.catalog.replace_repository(scan_result)
    other = Repository("other", "repo")
    duplicate = replace(scan_result.skills[0], path="a & copy/SKILL.md")
    state.catalog.replace_repository(replace(scan_result, repository=other, skills=(duplicate,)))
    before = state.catalog.path.read_bytes()
    home = client.get("/", params={"q": "CODE maintain"})
    assert home.status_code == 200
    assert "2 matching skills across 2 repositories" in home.text
    assert "1 of 2 skills" in home.text and "1 of 1 skill" in home.text
    assert "release-notes" not in home.text
    assert "<code>a &amp; copy/SKILL.md</code>" not in home.text
    assert "skill_path=a+%26+copy%2FSKILL.md" in home.text
    assert "q=CODE+maintain" in home.text
    filtered = client.get("/fragments/repositories", params={"q": "release"})
    assert "other/repo" not in filtered.text
    assert "1 matching skill across 1 repository" in filtered.text
    unfiltered = client.get("/")
    assert "code-review" not in unfiltered.text  # Collapsed metadata is loaded on demand.
    for route in ("/fragments/repository-skills", "/fragments/skills", "/repository"):
        result = client.get(route, params={"repository_url": other.url, "q": "CODE maintain"})
        assert result.status_code == 200 and "code-review" in result.text
        assert "release-notes" not in result.text
    selected = client.get(
        "/repository",
        params={
            "repository_url": scan_result.repository.url,
            "q": "notes",
            "skill_path": scan_result.skills[0].path,
        },
    )
    assert 'data-selected-path="review/SKILL.md"' in selected.text
    assert 'class="filter-notice" >The open skill is hidden' in selected.text
    assert 'hx-trigger="load"' in selected.text
    assert state.catalog.path.read_bytes() == before
    assert not state.requests


def test_filter_empty_literal_queries_errors_and_scan_refresh(client, web_environment, scan_result):
    state = web_environment
    state.catalog.replace_repository(scan_result)
    for q in ("SKILL.md", "acme", "%", "_", "<script>alert(1)</script>"):
        result = client.get("/fragments/repositories", params={"q": q})
        assert result.status_code == 200
        assert "No skills match" in result.text and "Clear filter" in result.text
        assert "<script>alert" not in result.text
        assert 'class="repository-row"' not in result.text
    empty = client.get("/fragments/repositories", params={"q": " \t "})
    assert "No skills match" not in empty.text and "Acme/skills" in empty.text
    wait_scan(client, submit(client))
    assert "2 matching skills" in client.get("/fragments/repositories", params={"q": "review"}).text
    state.zero = True
    wait_scan(client, submit(client))
    assert "No skills match" in client.get("/fragments/repositories", params={"q": "review"}).text
    assert "No repositories" in client.get("/").text
    state.catalog.path.write_bytes(b"broken database")
    for route, params in (
        ("/fragments/repositories", {"q": "review"}),
        ("/fragments/repository-skills", {"repository_url": scan_result.repository.url}),
        ("/fragments/skills", {"repository_url": scan_result.repository.url, "q": "review"}),
    ):
        response = client.get(route, params=params, headers={"HX-Request": "true"})
        assert response.status_code == 500 and "catalog_error" in response.text
        assert "No skills match" not in response.text


@pytest.mark.parametrize("route", ["/repository", "/fragments/repository", "/fragments/skills"])
@pytest.mark.parametrize(
    "query, count", [("", "2 skills"), ("review", "1 of 2 skills"), ("absent", "0 of 2 skills")]
)
def test_repository_count_uses_same_filtered_snapshot(
    client, web_environment, scan_result, route, query, count
):
    web_environment.catalog.replace_repository(scan_result)
    response = client.get(route, params={"repository_url": scan_result.repository.url, "q": query})
    assert response.status_code == 200
    assert f'data-skill-count="{count}"' in response.text
    assert 'class="filter-count"' not in response.text
    if route != "/fragments/skills":
        assert f'id="skill-count" role="status">{count}</span>' in response.text
        assert response.text.index('id="skill-count"') < response.text.index('id="skill-filter"')
    assert not web_environment.requests


def test_organization_scans_report_progress_failures_and_reuse_active_jobs(
    client, web_environment, scan_result
):
    state = web_environment
    state.organization = ["skills", "tools"]
    state.scan_gate.clear()
    first = submit(client, "https://github.com/Acme/")
    assert first.status_code == 202
    assert (
        submit(client, "https://github.com/acme").headers["Location"] == first.headers["Location"]
    )
    running = wait_scan(client, first, "running")
    assert "Scanning 0 of 2 repositories" in running.text
    assert "data-catalog-changed" not in running.text
    state.scan_gate.set()
    done = wait_scan(client, first)
    assert "2 repositories scanned · 4 skills found" in done.text
    assert 'data-organization="https://github.com/acme"' in done.text
    assert "View results" not in done.text
    assert {summary.repository.url for summary in state.catalog.repositories()} == {
        "https://github.com/acme/skills",
        "https://github.com/acme/tools",
    }
    # Browsing the organization's results does not trigger another scan.
    requests = len(state.requests)
    assert "Acme/tools" in client.get("/").text
    assert len(state.requests) == requests

    before = state.catalog.skills(Repository("acme", "tools"))
    state.commit = "d" * 40
    state.failed_repositories = {"Acme/tools"}
    failed = wait_scan(client, submit(client, "https://github.com/Acme"), "failed")
    assert "Failed — 1 repository failed." in failed.text
    assert "<strong>Acme/tools</strong> — GitHub request failed (HTTP 503)" in failed.text
    assert "data-catalog-changed" in failed.text
    assert 'name="repository_url" value="https://github.com/acme"' in failed.text
    assert state.catalog.skills(Repository("acme", "tools")) == before
    assert state.catalog.skills(Repository("acme", "skills"))[0].commit_sha == "d" * 40


def test_organization_job_waits_for_listing_and_reports_listing_errors(client, web_environment):
    from unittest.mock import patch

    from skill_atlas import runtime

    state = web_environment
    state.listing_gate.clear()
    response = submit(client, "https://github.com/acme")
    assert "Listing repositories…" in wait_scan(client, response, "running").text
    state.listing_gate.set()
    wait_scan(client, response)

    with patch.object(runtime, "github_token", lambda: None):
        failed = wait_scan(client, submit(client, "https://github.com/acme"), "failed")
    assert "require a GitHub credential" in failed.text
    assert "data-catalog-changed" in failed.text


def test_invalid_scan_targets_mention_organization_urls(client):
    invalid = submit(client, "https://github.com/")
    assert invalid.status_code == 400
    assert "https://github.com/organization" in invalid.text
