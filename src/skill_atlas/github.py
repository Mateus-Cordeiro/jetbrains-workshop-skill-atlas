"""GitHub REST adapter. All content reads use immutable tree/blob identifiers."""

import base64
import binascii
import re
from collections.abc import Iterable
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import quote

import httpx

from skill_atlas.errors import IncompleteListingError, RepositoryError
from skill_atlas.models import Repository, Skill, SkillFile, Snapshot


def _object(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RepositoryError("GitHub returned an invalid response; the catalog was not updated.")
    return value


def _string(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise RepositoryError("GitHub returned incomplete metadata; the catalog was not updated.")
    return value


def _sha(data: dict[str, Any]) -> str:
    value = _string(data, "sha")
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise RepositoryError("GitHub returned an invalid Git object identifier.")
    return value


class GitHubReader:
    def __init__(self, client: httpx.Client) -> None:
        self.client = client

    def _request(
        self,
        path: str,
        *,
        params: dict[str, str] | None = None,
        accept: str = "application/vnd.github+json",
    ) -> httpx.Response:
        try:
            response = self.client.get(path, params=params, headers={"Accept": accept})
        except httpx.HTTPError as error:
            raise RepositoryError(
                "Could not reach GitHub. Check your connection and try again."
            ) from error
        if response.status_code in (403, 429):
            limited = (
                response.status_code == 429
                or response.headers.get("x-ratelimit-remaining") == "0"
                or "retry-after" in response.headers
                or "rate limit" in response.text.lower()
            )
            if limited:
                raise RepositoryError(
                    "GitHub's rate limit was reached. "
                    "Retry later, or configure a GitHub credential."
                )
            raise RepositoryError(
                "GitHub denied access. Check the credential's repository permissions."
            )
        if response.status_code == 401:
            raise RepositoryError(
                "GitHub authentication failed. Check your token or GitHub CLI login."
            )
        if response.status_code == 404:
            raise RepositoryError(
                "GitHub repository or content not found. "
                "Check the URL and private repository access."
            )
        if response.status_code == 409:
            raise RepositoryError("GitHub could not resolve a commit; the repository may be empty.")
        if not response.is_success:
            raise RepositoryError(
                f"GitHub request failed (HTTP {response.status_code}). Try again later."
            )
        return response

    def _get(self, path: str, *, params: dict[str, str] | None = None) -> dict[str, Any]:
        response = self._request(path, params=params)
        try:
            return _object(response.json())
        except ValueError as error:
            raise RepositoryError(
                "GitHub returned invalid JSON; the catalog was not updated."
            ) from error

    def read_document(self, skill: Skill) -> bytes:
        response = self._request(
            f"/repos/{skill.repository.full_name}/contents/{quote(skill.path, safe='/')}",
            params={"ref": skill.commit_sha},
            accept="application/vnd.github.raw+json",
        )
        if response.headers.get("content-type", "").split(";")[0] == "application/json":
            raise RepositoryError("GitHub returned metadata instead of a skill document.")
        return response.content

    def resolve(self, repository: Repository) -> Snapshot:
        metadata = self._get(f"/repos/{repository.full_name}")
        full_name = _string(metadata, "full_name")
        try:
            canonical = Repository.from_url(f"https://github.com/{full_name}")
        except ValueError as error:
            raise RepositoryError("GitHub returned an invalid repository name.") from error
        branch = quote(_string(metadata, "default_branch"), safe="")
        commit = self._get(f"/repos/{canonical.full_name}/commits/{branch}")
        tree = _object(_object(commit.get("commit")).get("tree"))
        return Snapshot(canonical, _sha(commit), _sha(tree))

    def _tree(
        self, snapshot: Snapshot, sha: str, *, recursive: bool
    ) -> tuple[list[dict[str, Any]], bool]:
        data = self._get(
            f"/repos/{snapshot.repository.full_name}/git/trees/{sha}",
            params={"recursive": "1"} if recursive else None,
        )
        if not isinstance(data.get("truncated"), bool) or not isinstance(data.get("tree"), list):
            raise RepositoryError("GitHub returned an incomplete file listing.")
        return [_object(entry) for entry in data["tree"]], data["truncated"]

    @staticmethod
    def _file(entry: dict[str, Any]) -> SkillFile | None:
        path = _string(entry, "path")
        mode, kind = _string(entry, "mode"), _string(entry, "type")
        if kind == "blob" and mode in ("100644", "100755"):
            if PurePosixPath(path).name == "SKILL.md":
                return SkillFile(path, _sha(entry))
        return None

    def skill_files(self, snapshot: Snapshot) -> Iterable[SkillFile]:
        entries, truncated = self._tree(snapshot, snapshot.tree_sha, recursive=True)
        if truncated:
            # Do not yield partial results or spend one HTTP request per directory.
            raise IncompleteListingError("GitHub truncated the repository's file listing.")
        for entry in entries:
            file = self._file(entry)
            if file is not None:
                yield file

    def read_file(self, snapshot: Snapshot, file: SkillFile) -> bytes:
        data = self._get(f"/repos/{snapshot.repository.full_name}/git/blobs/{file.blob_sha}")
        if data.get("encoding") != "base64" or not isinstance(data.get("content"), str):
            raise RepositoryError(
                "GitHub returned unreadable skill content; the catalog was not updated."
            )
        try:
            # GitHub inserts newlines into its base64 representation.
            return base64.b64decode("".join(data["content"].split()), validate=True)
        except (ValueError, binascii.Error) as error:
            raise RepositoryError("GitHub returned corrupt skill content.") from error
