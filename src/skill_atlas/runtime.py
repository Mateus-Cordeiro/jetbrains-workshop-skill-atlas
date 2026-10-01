"""Composition root: select and configure concrete adapters in one place."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from math import isfinite
from threading import Event

import httpx
from fastapi import FastAPI

from skill_atlas.adapters.credentials import github_token
from skill_atlas.adapters.frontmatter import FrontmatterParser
from skill_atlas.adapters.git import GitSnapshotReader
from skill_atlas.adapters.github import GitHubOrganizationReader, GitHubReader
from skill_atlas.adapters.ollama import OllamaGrouping
from skill_atlas.adapters.storage.grouping import SQLiteGroups
from skill_atlas.adapters.storage.sqlite import SQLiteCatalog
from skill_atlas.application.catalog import BrowseCatalog
from skill_atlas.application.documents import Documents
from skill_atlas.application.grouping import SkillGroups
from skill_atlas.application.grouping_jobs import GroupingJobs
from skill_atlas.application.organization_scan import (
    OrganizationProgress,
    OrganizationScanner,
    OrganizationScanResult,
    SnapshotScan,
)
from skill_atlas.application.reader_fallback import FallbackReader
from skill_atlas.application.scan import Scanner
from skill_atlas.application.scan_jobs import ScanJobs
from skill_atlas.application.similarity import SimilarSkills
from skill_atlas.config import Settings
from skill_atlas.errors import GroupingError, RepositoryError, ScanCancelled
from skill_atlas.grouping import Grouping
from skill_atlas.models import Organization, Repository, ScanResult, Snapshot


def create_catalog_browser(settings: Settings) -> BrowseCatalog:
    return BrowseCatalog(SQLiteCatalog(settings.database_path))


def _github_client(
    settings: Settings, token: str | None, cancelled: Event | None = None
) -> httpx.Client:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "skill-atlas",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    def check_cancelled(request: httpx.Request) -> None:
        if cancelled is not None and cancelled.is_set():
            raise ScanCancelled("The scan was stopped before it finished.")

    return httpx.Client(
        base_url="https://api.github.com",
        headers=headers,
        timeout=settings.request_timeout,
        follow_redirects=True,
        event_hooks={"request": [check_cancelled]},
    )


def _snapshot_scanner(
    settings: Settings, client: httpx.Client, git_reader: GitSnapshotReader
) -> Scanner:
    return Scanner(
        FallbackReader(GitHubReader(client), git_reader),
        FrontmatterParser(),
        SQLiteCatalog(settings.database_path),
    )


@contextmanager
def create_scanner(settings: Settings) -> Iterator[Scanner]:
    token = github_token()
    with (
        _github_client(settings, token) as client,
        GitSnapshotReader(token, timeout=settings.git_timeout) as git_reader,
    ):
        yield _snapshot_scanner(settings, client, git_reader)


@contextmanager
def create_organization_scanner(settings: Settings) -> Iterator[OrganizationScanner]:
    token = github_token()
    if not token:
        raise RepositoryError(
            "Organization scans require a GitHub credential. Set GH_TOKEN or GITHUB_TOKEN, "
            "or log in with the GitHub CLI."
        )

    @contextmanager
    def worker(cancelled: Event) -> Iterator[SnapshotScan]:
        # Each worker owns one HTTP client; Git snapshots are released per repository.
        with _github_client(settings, token, cancelled) as client:

            def scan(snapshot: Snapshot) -> ScanResult:
                with GitSnapshotReader(
                    token, timeout=settings.git_timeout, cancelled=cancelled
                ) as git_reader:
                    scanner = _snapshot_scanner(settings, client, git_reader)
                    return scanner.scan_snapshot(snapshot)

            yield scan

    with _github_client(settings, token) as client:
        yield OrganizationScanner(GitHubOrganizationReader(client), worker)


def create_similarity(settings: Settings) -> SimilarSkills:
    """Wire a local, read-only search without credential or network setup."""
    return SimilarSkills(SQLiteCatalog(settings.database_path))


def _ollama_limits(settings: Settings) -> tuple[float, int, int]:
    timeout_error = "SKILL_ATLAS_OLLAMA_TIMEOUT must be a finite positive number of seconds."
    try:
        timeout = float(settings.ollama_timeout)
    except ValueError as error:
        raise GroupingError(timeout_error) from error
    if not isfinite(timeout) or timeout <= 0:
        raise GroupingError(timeout_error)

    def positive_integer(value: int | str, variable: str) -> int:
        message = f"{variable} must be a positive integer number of tokens."
        try:
            parsed = int(value)
        except ValueError as error:
            raise GroupingError(message) from error
        if parsed <= 0:
            raise GroupingError(message)
        return parsed

    context = positive_integer(settings.ollama_context, "SKILL_ATLAS_OLLAMA_CONTEXT")
    output = positive_integer(settings.ollama_output_tokens, "SKILL_ATLAS_OLLAMA_OUTPUT_TOKENS")
    if output >= context:
        raise GroupingError(
            "SKILL_ATLAS_OLLAMA_CONTEXT must be greater than SKILL_ATLAS_OLLAMA_OUTPUT_TOKENS."
        )
    return timeout, context, output


def create_web_app(settings: Settings) -> FastAPI:
    from skill_atlas.web.app import create_app

    catalog = SQLiteCatalog(settings.database_path)
    groups = SkillGroups(SQLiteGroups(catalog))

    def generate() -> tuple[Grouping, ...]:
        timeout, context, output = _ollama_limits(settings)
        endpoint = httpx.URL(settings.ollama_url)
        if (
            endpoint.scheme != "http"
            or endpoint.host not in {"127.0.0.1", "localhost", "::1"}
            or endpoint.userinfo
            or endpoint.query
            or endpoint.fragment
            or endpoint.path not in {"", "/"}
        ):
            raise GroupingError("Configure a local HTTP Ollama address.")
        with httpx.Client(
            base_url=settings.ollama_url,
            timeout=httpx.Timeout(timeout, connect=5),
            trust_env=False,
        ) as client:
            return groups.generate(
                OllamaGrouping(
                    client,
                    settings.ollama_model,
                    context=context,
                    output_tokens=output,
                ),
            )

    def scan(repository: Repository) -> ScanResult:
        with create_scanner(settings) as scanner:
            return scanner.scan(repository)

    def scan_organization(
        organization: Organization,
        progress: Callable[[OrganizationProgress], None],
        cancelled: Event,
    ) -> OrganizationScanResult:
        with create_organization_scanner(settings) as scanner:
            return scanner.scan(organization, progress=progress, cancelled=cancelled)

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
        catalog,
        ScanJobs(scan, scan_organization),
        documents,
        SimilarSkills(catalog),
        groups,
        GroupingJobs(generate),
    )
