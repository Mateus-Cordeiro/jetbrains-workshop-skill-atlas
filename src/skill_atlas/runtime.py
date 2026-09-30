"""Composition root: select and configure concrete adapters in one place."""

from collections.abc import Iterator
from contextlib import contextmanager

import httpx

from skill_atlas.auth import github_token
from skill_atlas.config import Settings
from skill_atlas.git import GitSnapshotReader
from skill_atlas.github import GitHubReader
from skill_atlas.parsing import FrontmatterParser
from skill_atlas.readers import FallbackReader
from skill_atlas.scanner import Scanner
from skill_atlas.storage.sqlite import SQLiteCatalog


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
