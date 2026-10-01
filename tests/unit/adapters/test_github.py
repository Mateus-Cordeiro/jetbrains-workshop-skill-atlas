import base64
import json

import httpx
import pytest

from skill_atlas.adapters.github import GitHubOrganizationReader, GitHubReader
from skill_atlas.errors import IncompleteListingError, RateLimitError, RepositoryError
from skill_atlas.models import Organization, Repository, SkillFile, Snapshot

COMMIT, TREE, BLOB, SUBTREE = (letter * 40 for letter in "abcd")


def entry(path, sha=BLOB, kind="blob", mode="100644"):
    return {"path": path, "sha": sha, "type": kind, "mode": mode}


def test_resolves_default_branch_and_reads_private_blob_at_snapshot(repository):
    requests = []

    def handler(request):
        requests.append(request)
        assert request.headers["Authorization"] == "Bearer test-token"
        if request.url.path == "/repos/Acme/skills":
            return httpx.Response(200, json={"full_name": "Acme/skills", "default_branch": "main"})
        if request.url.path.endswith("/commits/main"):
            return httpx.Response(200, json={"sha": COMMIT, "commit": {"tree": {"sha": TREE}}})
        if "/git/trees/" in request.url.path:
            assert request.url.path.endswith(TREE)
            assert request.url.params["recursive"] == "1"
            return httpx.Response(
                200,
                json={
                    "truncated": False,
                    "tree": [
                        entry("SKILL.md"),
                        entry("nested/SKILL.md"),
                        entry("lower/skill.md"),
                        entry("link/SKILL.md", mode="120000"),
                        entry("submodule", kind="commit", mode="160000"),
                    ],
                },
            )
        assert request.url.path.endswith(f"/git/blobs/{BLOB}")
        return httpx.Response(
            200,
            json={"encoding": "base64", "content": base64.b64encode(b"skill data").decode() + "\n"},
        )

    with httpx.Client(
        base_url="https://api.github.com",
        headers={"Authorization": "Bearer test-token"},
        transport=httpx.MockTransport(handler),
    ) as client:
        reader = GitHubReader(client)
        snapshot = reader.resolve(repository)
        files = list(reader.skill_files(snapshot))
        assert [file.path for file in files] == ["SKILL.md", "nested/SKILL.md"]
        assert reader.read_file(snapshot, files[0]) == b"skill data"
        assert snapshot.commit_sha == COMMIT
        assert len(requests) == 4


def test_truncated_listing_signals_fallback_without_yielding_partial_files(repository):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        assert request.url.params.get("recursive") == "1"
        return httpx.Response(200, json={"truncated": True, "tree": [entry("partial/SKILL.md")]})

    with httpx.Client(
        base_url="https://api.github.com", transport=httpx.MockTransport(handler)
    ) as client:
        files = iter(GitHubReader(client).skill_files(Snapshot(repository, COMMIT, TREE)))
        with pytest.raises(IncompleteListingError):
            next(files)
    assert len(calls) == 1


@pytest.mark.parametrize("listing", [{"tree": []}, {"truncated": False}])
def test_incomplete_tree_cannot_be_a_success(repository, listing):
    with (
        httpx.Client(
            base_url="https://api.github.com",
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=listing)),
        ) as client,
        pytest.raises(RepositoryError, match="incomplete"),
    ):
        list(GitHubReader(client).skill_files(Snapshot(repository, COMMIT, TREE)))


@pytest.mark.parametrize(
    ("status", "headers", "message"),
    [
        (401, {}, "authentication"),
        (403, {}, "denied access"),
        (403, {"x-ratelimit-remaining": "0"}, "rate limit"),
        (403, {"retry-after": "60"}, "rate limit"),
        (429, {}, "rate limit"),
        (404, {}, "private repository access"),
        (409, {}, "empty"),
        (503, {}, "HTTP 503"),
    ],
)
def test_api_failures_have_actionable_errors(repository, status, headers, message):
    with (
        httpx.Client(
            base_url="https://api.github.com",
            transport=httpx.MockTransport(lambda request: httpx.Response(status, headers=headers)),
        ) as client,
        pytest.raises(RepositoryError, match=message),
    ):
        GitHubReader(client).resolve(repository)


def test_network_failure_is_translated(repository):
    def handler(request):
        raise httpx.ReadTimeout("timeout", request=request)

    with (
        httpx.Client(
            base_url="https://api.github.com", transport=httpx.MockTransport(handler)
        ) as client,
        pytest.raises(RepositoryError, match="connection"),
    ):
        GitHubReader(client).resolve(repository)


@pytest.mark.parametrize(
    "data",
    [{"encoding": "base64", "content": "not base64!"}, {"encoding": "none", "content": ""}],
)
def test_corrupt_blob_is_a_retrieval_failure(repository, data):
    with (
        httpx.Client(
            base_url="https://api.github.com",
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=data)),
        ) as client,
        pytest.raises(RepositoryError),
    ):
        GitHubReader(client).read_file(
            Snapshot(repository, COMMIT, TREE), SkillFile("SKILL.md", BLOB)
        )


def test_document_reader_rejects_metadata_instead_of_raw_file(scan_result):
    with httpx.Client(
        base_url="https://api.github.com",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"type": "dir"})),
    ) as client:
        with pytest.raises(RepositoryError, match="metadata"):
            GitHubReader(client).read_document(scan_result.skills[0])


def test_rate_limits_are_distinguishable_from_other_access_failures(repository):
    with (
        httpx.Client(
            base_url="https://api.github.com",
            transport=httpx.MockTransport(lambda request: httpx.Response(429)),
        ) as client,
        pytest.raises(RateLimitError),
    ):
        GitHubReader(client).resolve(repository)


def node(name, *, fork=False, archived=False, empty=False):
    branch = None if empty else {"target": {"oid": COMMIT, "tree": {"oid": TREE}}}
    return {
        "nameWithOwner": name,
        "isFork": fork,
        "isArchived": archived,
        "isEmpty": empty,
        "defaultBranchRef": branch,
    }


def owner(nodes, *, next_cursor=None, login="Acme", kind="Organization"):
    return {
        "data": {
            "repositoryOwner": {
                "__typename": kind,
                "login": login,
                "repositories": {
                    "pageInfo": {"hasNextPage": next_cursor is not None, "endCursor": next_cursor},
                    "nodes": nodes,
                },
            }
        }
    }


def list_with(*responses):
    requests = []
    pages = iter(responses)

    def handler(request):
        requests.append(json.loads(request.content))
        assert request.method == "POST" and request.url.path == "/graphql"
        response = next(pages)
        return (
            response if isinstance(response, httpx.Response) else httpx.Response(200, json=response)
        )

    with httpx.Client(
        base_url="https://api.github.com", transport=httpx.MockTransport(handler)
    ) as client:
        listing = GitHubOrganizationReader(client).list_repositories(Organization("acme"))
    return listing, requests


def test_organization_listing_pages_by_hundred_and_resolves_snapshots():
    first = [node(f"Acme/repo-{index:03}") for index in range(100)]
    second = [
        node("Acme/fork", fork=True),
        node("Acme/old", archived=True),
        node("Acme/new", empty=True),
    ]
    listing, requests = list_with(owner(first, next_cursor="page-2"), owner(second))

    assert [request["variables"]["first"] for request in requests] == [100, 100]
    assert [request["variables"]["after"] for request in requests] == [None, "page-2"]
    assert all(request["variables"]["login"] == "acme" for request in requests)
    assert listing.organization == Organization("Acme")
    assert len(listing.repositories) == 103
    repository = listing.repositories[0]
    assert repository.snapshot == Snapshot(Repository("Acme", "repo-000"), COMMIT, TREE)
    assert not repository.fork and not repository.archived
    fork, old, new = listing.repositories[-3:]
    assert fork.fork and old.archived
    assert new.snapshot is None


@pytest.mark.parametrize(
    ("response", "error", "message"),
    [
        ({"errors": [{"type": "RATE_LIMITED"}]}, RateLimitError, "rate limit"),
        (httpx.Response(403, headers={"x-ratelimit-remaining": "0"}), RateLimitError, "rate limit"),
        (httpx.Response(401), RepositoryError, "authentication"),
        (
            {"data": {"repositoryOwner": None}, "errors": [{"type": "NOT_FOUND"}]},
            RepositoryError,
            "acme was not found or is not visible",
        ),
        (owner([], kind="User"), RepositoryError, "user account"),
        ({"data": None, "errors": [{"type": "FORBIDDEN"}]}, RepositoryError, "organization access"),
        (owner([node("other/repo")]), RepositoryError, "another owner"),
        (owner([node("Acme/bad name")]), RepositoryError, "invalid repository name"),
        (owner([{**node("Acme/repo"), "isFork": "no"}]), RepositoryError, "invalid organization"),
        (
            owner([{**node("Acme/repo"), "defaultBranchRef": {"target": {"oid": "x"}}}]),
            RepositoryError,
            "identifier",
        ),
        (
            {"data": {"repositoryOwner": {"__typename": "Organization", "login": "Acme"}}},
            RepositoryError,
            "invalid response",
        ),
        (owner([node("Acme/repo")]) | {"data": []}, RepositoryError, "invalid response"),
        (
            {
                "data": {
                    "repositoryOwner": {
                        "__typename": "Organization",
                        "login": "Acme",
                        "repositories": {"nodes": None},
                    }
                }
            },
            RepositoryError,
            "invalid organization",
        ),
        (httpx.Response(200, text="not json"), RepositoryError, "invalid JSON"),
    ],
)
def test_organization_listing_failures_are_operational_errors(response, error, message):
    with pytest.raises(error, match=message):
        list_with(response)


def test_repeating_cursor_cannot_loop_forever():
    with pytest.raises(RepositoryError, match="repeating"):
        list_with(owner([], next_cursor="same"), owner([], next_cursor="same"))


def test_organization_listing_network_failure_is_translated():
    def handler(request):
        raise httpx.ConnectError("offline", request=request)

    with (
        httpx.Client(
            base_url="https://api.github.com", transport=httpx.MockTransport(handler)
        ) as client,
        pytest.raises(RepositoryError, match="connection"),
    ):
        GitHubOrganizationReader(client).list_repositories(Organization("acme"))
