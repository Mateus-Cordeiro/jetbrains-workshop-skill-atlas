"""Exercise installed entry points and Web assets without external I/O."""

import base64
import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic, sleep
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
from rich.text import Text

import skill_atlas
from skill_atlas import runtime
from skill_atlas.adapters.storage.sqlite import SQLiteCatalog
from skill_atlas.config import Settings
from skill_atlas.models import ScanResult

SOURCE = "---\nname: installed-skill\ndescription: Installed wheel check.\n---\n# Skill document\n"
COMMIT = "a" * 40
REPOSITORY = "https://github.com/acme/skills"


def github_response(request):
    if request.url.host == "127.0.0.1":
        assert request.url.path == "/api/chat" and "Authorization" not in request.headers
        payload = json.loads(request.content)
        skills = json.loads(payload["messages"][1]["content"])
        return httpx.Response(
            200,
            json={
                "done": True,
                "message": {
                    "content": json.dumps(
                        {
                            "groups": [
                                {
                                    "title": "Installed capability",
                                    "skill_ids": [s["id"] for s in skills],
                                }
                            ]
                        }
                    )
                },
            },
        )
    assert request.url.host == "api.github.com"
    assert "Authorization" not in request.headers
    if request.url.path == "/repos/acme/skills/contents/SKILL.md":
        assert request.url.params["ref"] == COMMIT
        return httpx.Response(200, text=SOURCE)
    responses = {
        "/repos/acme/skills": {"full_name": "acme/skills", "default_branch": "main"},
        "/repos/acme/skills/commits/main": {
            "sha": COMMIT,
            "commit": {"tree": {"sha": "b" * 40}},
        },
        f"/repos/acme/skills/git/trees/{'b' * 40}": {
            "truncated": False,
            "tree": [{"path": "SKILL.md", "type": "blob", "mode": "100644", "sha": "c" * 40}],
        },
        f"/repos/acme/skills/git/blobs/{'c' * 40}": {
            "encoding": "base64",
            "content": base64.b64encode(SOURCE.encode()).decode(),
        },
    }
    return httpx.Response(200, json=responses[request.url.path])


client_type = httpx.Client


def github_client(**options):
    return client_type(**options, transport=httpx.MockTransport(github_response))


assert "site-packages" in str(Path(skill_atlas.__file__).resolve())
module_help = subprocess.run(
    [sys.executable, "-m", "skill_atlas", "--help"],
    capture_output=True,
    text=True,
    check=True,
)
assert all(command in module_help.stdout for command in ("scan", "serve", "filter", "similar"))
filter_help = subprocess.run(
    [str(Path(sys.executable).with_name("skill-atlas")), "filter", "--help"],
    capture_output=True,
    text=True,
    check=True,
)
filter_help_text = Text.from_ansi(filter_help.stdout).plain
assert all(option in filter_help_text for option in ("--repository", "--json", "--no-interactive"))
similar_help = subprocess.run(
    [str(Path(sys.executable).with_name("skill-atlas")), "similar", "--help"],
    capture_output=True,
    text=True,
    check=True,
)
assert all(
    option in Text.from_ansi(similar_help.stdout).plain for option in ("--json", "--no-interactive")
)
with (
    TemporaryDirectory() as directory,
    patch.object(runtime, "github_token", return_value=None),
    patch.object(runtime.httpx, "Client", github_client),
):
    with TestClient(
        runtime.create_web_app(Settings(Path(directory) / "catalog.sqlite3")),
        base_url="http://127.0.0.1",
    ) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert "Repositories" in page.text
        assert 'id="add-repository"' in page.text
        assert 'aria-controls="repository-form"' in page.text
        for asset in ("htmx.min.js", "HTMX-LICENSE.txt", "app.js", "filters.js", "app.css"):
            response = client.get(f"/static/{asset}")
            assert response.status_code == 200 and response.content
        accepted = client.post(
            "/scans",
            data={"repository_url": REPOSITORY},
            headers={"Origin": "http://127.0.0.1", "X-Atlas-Request": "1"},
        )
        assert accepted.status_code == 202
        deadline = monotonic() + 5
        while True:
            job = client.get(accepted.headers["Location"])
            assert job.status_code == 200
            if 'data-state="succeeded"' in job.text:
                break
            assert 'data-state="failed"' not in job.text and monotonic() < deadline, job.text
            sleep(0.01)
        for path in ("/repository", "/fragments/repository"):
            page = client.get(path, params={"repository_url": REPOSITORY})
            assert page.status_code == 200 and "installed-skill" in page.text
        for path in ("/similar", "/fragments/similar"):
            page = client.get(path, params={"repository_url": REPOSITORY, "skill_path": "SKILL.md"})
            assert page.status_code == 200 and "No similar skills found" in page.text
        catalog = SQLiteCatalog(Path(directory) / "catalog.sqlite3")
        original = catalog.skills()[0]
        catalog.replace_repository(
            ScanResult(
                original.repository, COMMIT, (original, replace(original, path="copy/SKILL.md"))
            )
        )
        for perspective in ("topics", "capabilities"):
            accepted_group = client.post(
                f"/groups/{perspective}/generate",
                headers={"Origin": "http://127.0.0.1", "X-Atlas-Request": "1"},
            )
            assert accepted_group.status_code == 202
            deadline = monotonic() + 5
            while True:
                status = client.get(accepted_group.headers["Location"])
                if 'data-state="succeeded"' in status.text:
                    break
                assert 'data-state="failed"' not in status.text and monotonic() < deadline, (
                    status.text
                )
                sleep(0.01)
            for prefix in ("", "/fragments"):
                grouped = client.get(f"{prefix}/groups/{perspective}")
                assert grouped.status_code == 200 and "Installed capability" in grouped.text
                assert "installed-skill" in grouped.text and "Regenerate groups" in grouped.text
        environment = dict(os.environ, SKILL_ATLAS_DB=str(catalog.path))
        for options in ([], ["--no-interactive"], ["--json"]):
            command = subprocess.run(
                [
                    str(Path(sys.executable).with_name("skill-atlas")),
                    "similar",
                    REPOSITORY,
                    "SKILL.md",
                    *options,
                ],
                env=environment,
                capture_output=True,
                text=True,
                check=True,
            )
            assert command.stderr == ""
            if "--json" in options:
                data = json.loads(command.stdout)
                assert data["source"]["commit_sha"] == COMMIT
                assert data["matches"][0]["display_score"] == 100
                assert data["matches"][0]["locations"][0]["skill_path"] == "copy/SKILL.md"
            else:
                assert "1. installed-skill · 100%" in command.stdout
                assert "copy/SKILL.md" in command.stdout
                assert original.description in command.stdout
        matches = client.get(
            "/similar", params={"repository_url": REPOSITORY, "skill_path": "SKILL.md"}
        )
        assert (
            matches.status_code == 200
            and '<meter class="similarity-meter score-high"' in matches.text
        )
        assert 'aria-valuetext="100% similarity"' in matches.text
        assert 'class="skill-description"' in matches.text
        assert original.description in matches.text
        assert 'class="description-toggle"' in matches.text
        assert "acme/skills" in client.get("/fragments/repositories").text
        filtered = client.get("/", params={"q": "installed wheel"})
        assert "2 matching skills across 1 repository" in filtered.text
        cli_filtered = subprocess.run(
            [
                str(Path(sys.executable).with_name("skill-atlas")),
                "filter",
                "installed wheel",
                "--repository",
                REPOSITORY,
                "--json",
            ],
            env=dict(os.environ, SKILL_ATLAS_DB=str(catalog.path)),
            capture_output=True,
            text=True,
            check=True,
        )
        payload = json.loads(cli_filtered.stdout)
        assert payload["matching_count"] == 2
        assert [skill["skill_path"] for skill in payload["skills"]] == ["SKILL.md", "copy/SKILL.md"]
        assert all(skill["commit_sha"] == COMMIT for skill in payload["skills"])
        assert cli_filtered.stderr == ""
        printed_filter = subprocess.run(
            [str(Path(sys.executable).with_name("skill-atlas")), "filter", "--no-interactive"],
            env=environment,
            capture_output=True,
            text=True,
            check=True,
        )
        assert "2 matching skills" in printed_filter.stdout
        assert "1. installed-skill" in printed_filter.stdout
        assert original.description in printed_filter.stdout
        assert "copy/SKILL.md" in printed_filter.stdout
        assert printed_filter.stderr == "" and "\x1b" not in printed_filter.stdout
        for path in ("/fragments/skills", "/fragments/repository-skills"):
            result = client.get(path, params={"repository_url": REPOSITORY, "q": "installed"})
            assert result.status_code == 200 and "installed-skill" in result.text
        selection = {"repository_url": REPOSITORY, "skill_path": "SKILL.md", "commit_sha": COMMIT}
        document = client.get("/fragments/document", params=selection)
        assert document.status_code == 200 and "<h1>Skill document</h1>" in document.text
        assert 'id="document-source"' in document.text
        stale = client.get("/fragments/document", params={**selection, "commit_sha": "d" * 40})
        assert stale.status_code == 409 and "stale_skill" in stale.text
        for headers in ({}, {"HX-Request": "true"}):
            error = client.get("/repository", headers=headers)
            assert error.status_code == 400 and "invalid_input" in error.text
print(
    "Installed wheel runs similarity CLI, scan jobs, catalog pages, documents, and static assets."
)
