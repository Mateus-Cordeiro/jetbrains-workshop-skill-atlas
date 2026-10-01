import sqlite3
from dataclasses import replace
from time import monotonic, sleep

import pytest
from fastapi.testclient import TestClient

from skill_atlas.adapters.storage.grouping import SQLiteGroups
from skill_atlas.adapters.storage.migrations import MIGRATIONS
from skill_atlas.adapters.storage.sqlite import SQLiteCatalog
from skill_atlas.application.grouping import SkillGroups
from skill_atlas.config import Settings
from skill_atlas.errors import CatalogError
from skill_atlas.grouping import Perspective, SkillIdentity
from skill_atlas.models import Repository

HEADERS = {"Origin": "http://127.0.0.1", "X-Atlas-Request": "1"}


@pytest.fixture
def client(web_environment):
    with TestClient(web_environment.app, base_url="http://127.0.0.1") as client:
        yield client


def generate(client, perspective="capabilities", expected="succeeded"):
    accepted = client.post("/explore/generate", headers=HEADERS)
    return wait_group(client, accepted, expected)


def wait_group(client, accepted, expected="succeeded"):
    assert accepted.status_code == 202
    deadline = monotonic() + 5
    while monotonic() < deadline:
        status = client.get(accepted.headers["Location"])
        if f'data-state="{expected}"' in status.text:
            return status
        sleep(0.01)
    pytest.fail(status.text)


def test_explicit_generation_both_perspectives_persists_without_network_on_browse(
    client, web_environment, scan_result
):
    state = web_environment
    state.catalog.replace_repository(scan_result)
    for perspective in ("topics", "capabilities"):
        page = client.get(f"/groups/{perspective}")
        assert page.status_code == 200 and "Generate groups" in page.text
    assert state.grouping_requests == [] and state.requests == []
    state.grouping_content_by_perspective["topics"] = {
        "groups": [{"title": "Software development", "skill_ids": ["s1", "s2"]}]
    }
    generate(client)
    for perspective, title in [
        ("capabilities", "Improve software"),
        ("topics", "Software development"),
    ]:
        for prefix in ("", "/fragments"):
            page = client.get(f"{prefix}/explore", params={"perspective": perspective})
            assert page.status_code == 200 and title in page.text
            assert "Regenerate groups" in page.text
            assert "code-review" in page.text and "release-notes" in page.text
            assert 'id="graph-stale" class="group-stale" hidden' in page.text
        # A new service/adapter instance sees the saved generation.
        view = SkillGroups(SQLiteGroups(SQLiteCatalog(state.catalog.path))).browse(
            Perspective(perspective)
        )
        assert view.groups[0].title == title and view.skill_count == 2
    assert len(state.grouping_requests) == 2 and state.requests == []
    assert "fixture-token" not in state.catalog.path.read_bytes().decode(errors="ignore")


def test_selection_overlap_same_names_encoded_paths_and_escaped_output(
    client, web_environment, scan_result
):
    state = web_environment
    unusual = replace(scan_result.skills[0], path="copy #? /SKILL.md", name="<script>bad</script>")
    state.catalog.replace_repository(replace(scan_result, skills=(*scan_result.skills, unusual)))
    other = Repository("other", "repo")
    state.catalog.replace_repository(
        replace(scan_result, repository=other, skills=(scan_result.skills[0],))
    )
    state.grouping_content = {
        "groups": [
            {"title": "<img src=x onerror=bad()>", "skill_ids": ["s1", "s2", "s4"]},
            {"title": "Release software", "skill_ids": ["s2", "s3"]},
        ]
    }
    generate(client)
    page = client.get("/explore")
    assert "&lt;img" in page.text and "<img src=x" not in page.text
    assert "&lt;script&gt;bad&lt;/script&gt;" in page.text
    assert "copy+%23%3F+%2FSKILL.md" in page.text
    assert not state.requests
    import html
    import json
    import re

    payload = json.loads(html.unescape(re.search(r'data-graph="([^"]+)"', page.text)[1]))
    graph = payload["perspectives"]["capabilities"]
    assert len(graph["skills"]) == 4
    assert len({s["id"] for s in graph["skills"]}) == 4
    assert len(set(graph["groups"][0]["members"]) & set(graph["groups"][1]["members"])) == 1
    detail = client.get(
        "/groups/capabilities",
        params={
            "selected_repository": unusual.repository.url,
            "selected_path": unusual.path,
        },
    )
    assert "Back to Explore" in detail.text and 'hx-trigger="load"' in detail.text
    document = client.get(
        "/fragments/document",
        params={
            "repository_url": unusual.repository.url,
            "skill_path": unusual.path,
            "commit_sha": unusual.commit_sha,
        },
    )
    assert document.status_code == 200
    assert state.requests[-1].url.params["ref"] == unusual.commit_sha
    assert "source" not in state.catalog.path.read_bytes().decode(errors="ignore")


def test_failed_regeneration_preserves_previous_generation_and_is_retryable(
    client, web_environment, scan_result
):
    state = web_environment
    state.catalog.replace_repository(scan_result)
    generate(client)
    before = state.catalog.path.read_bytes()
    state.grouping_content = {"groups": [{"title": "Missing a skill", "skill_ids": ["s1"]}]}
    assert "incomplete or invalid" in generate(client, expected="failed").text
    assert state.catalog.path.read_bytes() == before
    assert "Improve software" in client.get("/groups/capabilities").text
    state.grouping_status = 404
    assert "configured model" in generate(client, expected="failed").text
    assert state.catalog.path.read_bytes() == before
    state.grouping_status, state.grouping_content = 200, None
    generate(client)


def test_scan_during_generation_marks_stale_and_documents_use_current_commit(
    client, web_environment, scan_result
):
    state = web_environment
    state.catalog.replace_repository(scan_result)
    state.grouping_gate.clear()
    try:
        accepted = client.post("/explore/generate", headers=HEADERS)
        deadline = monotonic() + 3
        while not state.grouping_requests and monotonic() < deadline:
            sleep(0.01)
        assert state.grouping_requests
        duplicate = client.post("/explore/generate", headers=HEADERS)
        assert accepted.headers["Location"] == duplicate.headers["Location"]
        updated = replace(
            scan_result,
            commit_sha="b" * 40,
            skills=(replace(scan_result.skills[0], name="changed", commit_sha="b" * 40),),
        )
        state.catalog.replace_repository(updated)
    finally:
        state.grouping_gate.set()
    wait_group(client, accepted)
    page = client.get("/explore?perspective=topics")
    assert "catalog has changed" in page.text
    assert "release-notes" not in page.text and "changed" in page.text
    detail = client.get(
        "/repository",
        params={
            "repository_url": updated.repository.url,
            "skill_path": updated.skills[0].path,
            "from_explore": "topics",
        },
    )
    assert "commit_sha=" + "b" * 40 in detail.text
    assert len(state.grouping_requests) == 2
    generate(client, "topics")
    assert 'id="graph-stale" class="group-stale" hidden' in client.get("/groups/topics").text
    state.catalog.replace_repository(replace(updated, skills=()))
    empty = client.get("/groups/topics")
    assert "No saved skills" in empty.text
    assert "release-notes" not in empty.text


def test_commit_only_change_does_not_require_regeneration(client, web_environment, scan_result):
    state = web_environment
    state.catalog.replace_repository(scan_result)
    generate(client)
    state.catalog.replace_repository(replace(scan_result, commit_sha="b" * 40))
    assert 'id="graph-stale" class="group-stale" hidden' in client.get("/groups/capabilities").text


def test_empty_missing_invalid_inputs_and_csrf_never_generate(client, web_environment):
    for perspective in ("topics", "capabilities"):
        assert "No saved skills" in client.get("/groups/" + perspective).text
    assert not web_environment.catalog.path.exists()
    assert client.get("/groups/unknown").status_code == 400
    assert client.get("/explore?perspective=unknown").status_code == 400
    for headers in ({}, {"Origin": "https://evil.test", "X-Atlas-Request": "1"}):
        assert client.post("/explore/generate", headers=headers).status_code == 403
    assert "No saved skills" in generate(client, "topics", "failed").text
    assert web_environment.grouping_requests == []
    assert not web_environment.catalog.path.exists()
    assert "failed" in client.get("/explore/status").text
    assert (
        client.get("/groups/topics", params={"selected_repository": "invalid"}).status_code == 400
    )


def test_v1_catalog_is_readable_without_mutation_and_generation_migrates(
    client, web_environment, scan_result
):
    path = web_environment.catalog.path
    with sqlite3.connect(path) as db:
        db.execute(MIGRATIONS[0].statements[0])
        db.execute("PRAGMA user_version=1")
        for s in scan_result.skills:
            db.execute(
                "INSERT INTO skills VALUES (?,?,?,?,?,?)",
                (
                    s.repository.url,
                    s.repository.full_name,
                    s.path,
                    s.name,
                    s.description,
                    s.commit_sha,
                ),
            )
    before = path.read_bytes()
    assert len(web_environment.catalog.skills()) == 2
    assert "Generate groups" in client.get("/groups/topics").text
    assert path.read_bytes() == before
    generate(client, "topics")
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 2
    assert web_environment.catalog.skills() == scan_result.skills


def test_save_failure_rolls_back_and_corrupt_group_data_is_an_error(
    client, web_environment, scan_result
):
    state = web_environment
    state.catalog.replace_repository(scan_result)
    generate(client)
    with sqlite3.connect(state.catalog.path) as db:
        db.execute(
            "CREATE TRIGGER fail_group BEFORE UPDATE ON skill_groupings "
            "WHEN NEW.perspective = 'capabilities' "
            "BEGIN SELECT RAISE(ABORT, 'fail'); END"
        )
    before = SQLiteGroups(state.catalog).read_all()
    state.grouping_content_by_perspective["topics"] = {
        "groups": [{"title": "Replacement topics", "skill_ids": ["s1", "s2"]}]
    }
    assert "Could not save" in generate(client, expected="failed").text
    assert SQLiteGroups(state.catalog).read_all() == before
    with sqlite3.connect(state.catalog.path) as db:
        db.execute("DROP TRIGGER fail_group")
        db.execute("UPDATE skill_groupings SET groups_json='{}'")
    assert client.get("/groups/capabilities").status_code == 500


def test_old_group_selection_disappears_when_removed_from_catalog(
    client, web_environment, scan_result
):
    state = web_environment
    state.catalog.replace_repository(scan_result)
    generate(client)
    state.catalog.replace_repository(replace(scan_result, skills=scan_result.skills[1:]))
    service = SkillGroups(SQLiteGroups(state.catalog))
    view = service.browse(Perspective.CAPABILITIES, SkillIdentity.of(scan_result.skills[0]))
    assert view.selected is None and view.stale
    assert view.groups[0].skills == scan_result.skills[1:]


def test_configuration_from_environment(monkeypatch, tmp_path):
    values = {
        "URL": "http://localhost:1234",
        "MODEL": "custom:latest",
        "TIMEOUT": "120",
        "CONTEXT": "65536",
        "OUTPUT_TOKENS": "9000",
    }
    for name, value in values.items():
        monkeypatch.setenv("SKILL_ATLAS_OLLAMA_" + name, value)
    settings = Settings.from_environment()
    assert settings.ollama_url == values["URL"] and settings.ollama_model == values["MODEL"]
    assert settings.ollama_timeout == 120 and settings.ollama_context == 65536
    assert settings.ollama_output_tokens == 9000


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://evil.test",
        "http://user:secret@localhost:11434",
        "http://localhost:11434/path",
        "http://localhost:11434/?q=x",
    ],
)
def test_nonlocal_or_credential_bearing_endpoints_rejected(web_environment, scan_result, endpoint):
    from skill_atlas.runtime import create_web_app

    state = web_environment
    state.catalog.replace_repository(scan_result)
    with TestClient(
        create_web_app(replace(state.settings, ollama_url=endpoint)), base_url="http://127.0.0.1"
    ) as client:
        assert "local HTTP" in generate(client, expected="failed").text
    assert state.grouping_requests == []


@pytest.mark.parametrize("content", ["not json", "null", "[{}]", '[{"title": 1,"members":[]}]'])
def test_corrupt_persisted_groups_are_not_empty_catalog(tmp_path, scan_result, content):
    catalog = SQLiteCatalog(tmp_path / "catalog.sqlite3")
    catalog.replace_repository(scan_result)
    with sqlite3.connect(catalog.path) as db:
        db.execute(
            "INSERT INTO skill_groupings VALUES (?,?,?,?)",
            ("topics", "fingerprint", "model", content),
        )
    with pytest.raises(CatalogError, match="invalid"):
        SQLiteGroups(catalog).read(Perspective.TOPICS)


def test_invalid_second_result_keeps_both_saved_perspectives(client, web_environment, scan_result):
    state = web_environment
    state.catalog.replace_repository(scan_result)
    generate(client)
    before = SQLiteGroups(state.catalog).read_all()
    state.grouping_content_by_perspective = {
        "topics": {"groups": [{"title": "New topics", "skill_ids": ["s1", "s2"]}]},
        "capabilities": {"groups": [{"title": "Incomplete", "skill_ids": ["s1"]}]},
    }
    assert "incomplete or invalid" in generate(client, expected="failed").text
    assert SQLiteGroups(state.catalog).read_all() == before
    assert len(state.grouping_requests) == 4


def test_graph_assets_local_and_legacy_navigation_is_safe(client, web_environment, scan_result):
    web_environment.catalog.replace_repository(scan_result)
    page = client.get("/explore")
    assert "/static/g6.min.js" in page.text and "/static/explore.js" in page.text
    assert "unsafe-eval" not in page.headers["content-security-policy"]
    assert "https://" not in page.text
    for path in ["g6.min.js", "g6-LICENSE.txt", "explore.js", "explore.css"]:
        assert client.get("/static/" + path).status_code == 200
    assert "@antv/g6 5.1.1" in client.get("/static/g6.min.js").text
    response = client.get("/groups/topics", follow_redirects=False)
    assert response.headers["location"] == "/explore?perspective=topics"
    page = client.get(
        "/repository",
        params={
            "repository_url": scan_result.repository.url,
            "skill_path": scan_result.skills[0].path,
            "from_explore": "https://evil.test",
        },
    )
    assert "evil.test" not in page.text and "Back to Explore" not in page.text


def test_explore_return_context_survives_repository_workspace_refresh(
    client, web_environment, scan_result
):
    web_environment.catalog.replace_repository(scan_result)
    params = {
        "repository_url": scan_result.repository.url,
        "skill_path": scan_result.skills[0].path,
        "from_explore": "topics",
    }
    for route in ("/repository", "/fragments/repository"):
        page = client.get(route, params=params)
        assert page.status_code == 200 and 'data-from-explore="topics"' in page.text
        assert 'data-selected-path="review/SKILL.md"' in page.text
