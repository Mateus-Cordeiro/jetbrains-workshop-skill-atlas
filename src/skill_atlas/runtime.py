"""Composition root: select and configure concrete adapters in one place."""

from collections.abc import Iterator
from contextlib import contextmanager

import httpx
from fastapi import FastAPI

from skill_atlas.adapters.credentials import github_token
from skill_atlas.adapters.frontmatter import FrontmatterParser
from skill_atlas.adapters.git import GitSnapshotReader
from skill_atlas.adapters.github import GitHubReader
from skill_atlas.adapters.ollama import OllamaGrouping
from skill_atlas.adapters.storage.grouping import SQLiteGroups
from skill_atlas.adapters.storage.sqlite import SQLiteCatalog
from skill_atlas.application.catalog import BrowseCatalog
from skill_atlas.application.documents import Documents
from skill_atlas.application.grouping import SkillGroups
from skill_atlas.application.grouping_jobs import GroupingJobs
from skill_atlas.application.reader_fallback import FallbackReader
from skill_atlas.application.scan import Scanner
from skill_atlas.application.scan_jobs import ScanJobs
from skill_atlas.application.similarity import SimilarSkills
from skill_atlas.config import Settings
from skill_atlas.errors import GroupingError
from skill_atlas.grouping import Grouping, Perspective
from skill_atlas.models import Repository, ScanResult


def create_catalog_browser(settings: Settings) -> BrowseCatalog:
    return BrowseCatalog(SQLiteCatalog(settings.database_path))


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


def create_similarity(settings: Settings) -> SimilarSkills:
    """Wire a local, read-only search without credential or network setup."""
    return SimilarSkills(SQLiteCatalog(settings.database_path))


def create_web_app(settings: Settings) -> FastAPI:
    from skill_atlas.web.app import create_app

    catalog = SQLiteCatalog(settings.database_path)
    groups = SkillGroups(SQLiteGroups(catalog))

    def generate(perspective: Perspective) -> Grouping:
        endpoint = httpx.URL(settings.ollama_url)
        if (
            endpoint.scheme != "http"
            or endpoint.host not in {"127.0.0.1", "localhost", "::1"}
            or endpoint.userinfo
            or endpoint.query
            or endpoint.fragment
            or endpoint.path not in {"", "/"}
            or settings.ollama_timeout <= 0
        ):
            raise GroupingError("Configure a local HTTP Ollama address and a positive timeout.")
        with httpx.Client(
            base_url=settings.ollama_url,
            timeout=httpx.Timeout(settings.ollama_timeout, connect=5),
            trust_env=False,
        ) as client:
            return groups.generate(
                perspective,
                OllamaGrouping(
                    client,
                    settings.ollama_model,
                    context=settings.ollama_context,
                    output_tokens=settings.ollama_output_tokens,
                ),
            )

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

    return create_app(
        catalog, ScanJobs(scan), documents, SimilarSkills(catalog), groups, GroupingJobs(generate)
    )
