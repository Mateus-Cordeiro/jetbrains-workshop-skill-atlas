"""GitHub REST and GraphQL adapter. Content reads use immutable tree/blob identifiers."""

import base64
import binascii
import re
from collections.abc import Iterable
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import quote

import httpx

from skill_atlas.errors import IncompleteListingError, RateLimitError, RepositoryError
from skill_atlas.models import (
    Organization,
    OrganizationListing,
    OrganizationRepository,
    Repository,
    RepositoryFile,
    Skill,
    SkillFile,
    Snapshot,
)

RATE_LIMITED = "GitHub's rate limit was reached. Retry later, or configure a GitHub credential."


def _object(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RepositoryError("GitHub returned an invalid response; the catalog was not updated.")
    return value


def _string(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise RepositoryError("GitHub returned incomplete metadata; the catalog was not updated.")
    return value


def _sha(data: dict[str, Any], key: str = "sha") -> str:
    value = _string(data, key)
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise RepositoryError("GitHub returned an invalid Git object identifier.")
    return value


def _checked(response: httpx.Response) -> httpx.Response:
    """Translate GitHub HTTP failures into operational errors without raw details."""
    if response.status_code in (403, 429):
        limited = (
            response.status_code == 429
            or response.headers.get("x-ratelimit-remaining") == "0"
            or "retry-after" in response.headers
            or "rate limit" in response.text.lower()
        )
        if limited:
            raise RateLimitError(RATE_LIMITED)
        raise RepositoryError(
            "GitHub denied access. Check the credential's repository permissions."
        )
    if response.status_code == 401:
        raise RepositoryError("GitHub authentication failed. Check your token or GitHub CLI login.")
    if response.status_code == 404:
        raise RepositoryError(
            "GitHub repository or content not found. Check the URL and private repository access."
        )
    if response.status_code == 409:
        raise RepositoryError("GitHub could not resolve a commit; the repository may be empty.")
    if not response.is_success:
        raise RepositoryError(
            f"GitHub request failed (HTTP {response.status_code}). Try again later."
        )
    return response


def _json(response: httpx.Response) -> dict[str, Any]:
    try:
        return _object(response.json())
    except ValueError as error:
        raise RepositoryError(
            "GitHub returned invalid JSON; the catalog was not updated."
        ) from error


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
        return _checked(response)

    def _get(self, path: str, *, params: dict[str, str] | None = None) -> dict[str, Any]:
        return _json(self._request(path, params=params))

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

    def resolve_commit(self, repository: Repository, commit_sha: str) -> Snapshot:
        from skill_atlas.installation import checked_commit

        checked_commit(commit_sha)
        commit = self._get(f"/repos/{repository.full_name}/commits/{commit_sha}")
        if _sha(commit) != commit_sha:
            raise RepositoryError("GitHub returned a different commit than the catalog recorded.")
        tree = _object(_object(commit.get("commit")).get("tree"))
        return Snapshot(repository, commit_sha, _sha(tree))

    def regular_files(self, snapshot: Snapshot) -> tuple[RepositoryFile, ...]:
        entries, truncated = self._tree(snapshot, snapshot.tree_sha, recursive=True)
        if truncated:
            raise IncompleteListingError("GitHub truncated the repository's file listing.")
        return tuple(
            RepositoryFile(_string(entry, "path"), _sha(entry), entry["mode"] == "100755")
            for entry in entries
            if _string(entry, "type") == "blob" and _string(entry, "mode") in {"100644", "100755"}
        )

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


_ORGANIZATION_QUERY = """
query OrganizationRepositories($login: String!, $first: Int!, $after: String) {
  repositoryOwner(login: $login) {
    __typename
    login
    ... on Organization {
      repositories(first: $first, after: $after, orderBy: {field: NAME, direction: ASC}) {
        pageInfo { hasNextPage endCursor }
        nodes {
          nameWithOwner
          isFork
          isArchived
          isEmpty
          defaultBranchRef { target { ... on Commit { oid tree { oid } } } }
        }
      }
    }
  }
}
"""


def _flag(data: dict[str, Any], key: str) -> bool:
    value = data.get(key)
    if not isinstance(value, bool):
        raise RepositoryError("GitHub returned an invalid organization repository listing.")
    return value


class GitHubOrganizationReader:
    """List organization repositories with their default-branch snapshots via GraphQL."""

    def __init__(self, client: httpx.Client, *, page_size: int = 100) -> None:
        self.client = client
        self.page_size = page_size

    def _page(self, organization: Organization, after: str | None) -> dict[str, Any]:
        try:
            response = self.client.post(
                "/graphql",
                json={
                    "query": _ORGANIZATION_QUERY,
                    "variables": {
                        "login": organization.login,
                        "first": self.page_size,
                        "after": after,
                    },
                },
            )
        except httpx.HTTPError as error:
            raise RepositoryError(
                "Could not reach GitHub. Check your connection and try again."
            ) from error
        data = _json(_checked(response))
        errors = data.get("errors")
        if isinstance(errors, list) and errors:
            kinds = {error.get("type") for error in errors if isinstance(error, dict)}
            if "RATE_LIMITED" in kinds:
                raise RateLimitError(RATE_LIMITED)
            if kinds != {"NOT_FOUND"}:
                raise RepositoryError(
                    "GitHub could not list the organization's repositories. "
                    "Check the credential's organization access."
                )
        owner = _object(data.get("data")).get("repositoryOwner")
        if owner is None:
            raise RepositoryError(
                f"GitHub organization {organization.login} was not found or is not visible "
                "to your credential."
            )
        if _object(owner).get("__typename") != "Organization":
            raise RepositoryError(
                f"{organization.login} is a GitHub user account. Only organizations can be "
                "scanned by owner URL; scan each repository by its URL instead."
            )
        return _object(owner)

    @staticmethod
    def _repository(organization: Organization, node: dict[str, Any]) -> OrganizationRepository:
        try:
            repository = Repository.from_url(f"https://github.com/{_string(node, 'nameWithOwner')}")
        except ValueError as error:
            raise RepositoryError("GitHub returned an invalid repository name.") from error
        if repository.owner.lower() != organization.login.lower():
            raise RepositoryError("GitHub listed a repository from another owner.")
        empty = _flag(node, "isEmpty")
        branch = node.get("defaultBranchRef")
        snapshot = None
        if not empty and branch is not None:
            commit = _object(_object(branch).get("target"))
            snapshot = Snapshot(
                repository, _sha(commit, "oid"), _sha(_object(commit.get("tree")), "oid")
            )
        return OrganizationRepository(
            repository, _flag(node, "isFork"), _flag(node, "isArchived"), snapshot
        )

    def list_repositories(self, organization: Organization) -> OrganizationListing:
        repositories: list[OrganizationRepository] = []
        after: str | None = None
        while True:
            owner = self._page(organization, after)
            canonical = Organization(_string(owner, "login"))
            listing = _object(owner.get("repositories"))
            nodes = listing.get("nodes")
            if not isinstance(nodes, list):
                raise RepositoryError("GitHub returned an invalid organization repository listing.")
            repositories.extend(self._repository(canonical, _object(node)) for node in nodes)
            page = _object(listing.get("pageInfo"))
            if not _flag(page, "hasNextPage"):
                return OrganizationListing(canonical, tuple(repositories))
            cursor = _string(page, "endCursor")
            if cursor == after:
                raise RepositoryError("GitHub returned a repeating organization listing.")
            after = cursor
