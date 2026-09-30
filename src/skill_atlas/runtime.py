"""Composition root: select and configure concrete adapters in one place."""

from collections.abc import Iterator
from contextlib import contextmanager

import httpx
from fastapi import FastAPI

from skill_atlas.adapters.credentials import github_token
from skill_atlas.adapters.frontmatter import FrontmatterParser
from skill_atlas.adapters.git import GitSnapshotReader
from skill_atlas.adapters.github import GitHubReader
from skill_atlas.adapters.storage.sqlite import SQLiteCatalog
from skill_atlas.application.documents import Documents
from skill_atlas.application.reader_fallback import FallbackReader
from skill_atlas.application.scan import Scanner
from skill_atlas.application.scan_jobs import ScanJobs
from skill_atlas.application.similarity import SimilarSkills
from skill_atlas.config import Settings
from skill_atlas.models import Repository, ScanResult


@contextmanager
def create_scanner(settings: Settings) -> Iterator[Scanner]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "skill-atlas",
    }
    token = github_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with (
        httpx.Client(
            base_url="https://api.github.com",
            headers=headers,
            timeout=settings.request_timeout,
            follow_redirects=True,
        ) as client,
        GitSnapshotReader(token, timeout=settings.git_timeout) as git_reader,
    ):
        yield Scanner(
            FallbackReader(GitHubReader(client), git_reader),
            FrontmatterParser(),
            SQLiteCatalog(settings.database_path),
        )


def create_web_app(settings: Settings) -> FastAPI:
    from skill_atlas.web.app import create_app

    catalog = SQLiteCatalog(settings.database_path)

    def scan(repository: Repository) -> ScanResult:
        with create_scanner(settings) as scanner:
            return scanner.scan(repository)

    @contextmanager
    def documents() -> Iterator[Documents]:
        token = github_token()
        headers = {"User-Agent": "skill-atlas", "X-GitHub-Api-Version": "2022-11-28"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        with httpx.Client(
            base_url="https://api.github.com",
            headers=headers,
            timeout=settings.request_timeout,
            follow_redirects=True,
        ) as client:
            yield Documents(catalog, GitHubReader(client))

    return create_app(catalog, ScanJobs(scan), documents, SimilarSkills(catalog))
