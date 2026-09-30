import base64

import httpx
import pytest

from skill_atlas.errors import IncompleteListingError, RepositoryError
from skill_atlas.github import GitHubReader
from skill_atlas.models import SkillFile, Snapshot

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
