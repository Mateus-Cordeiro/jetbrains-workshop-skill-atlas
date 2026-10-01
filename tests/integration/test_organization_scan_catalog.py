"""Organization scans through the CLI, GraphQL listing, worker pool, readers, and catalog."""

import _thread
import sqlite3
from threading import Barrier, BrokenBarrierError, Event
from time import monotonic, sleep

import httpx
import pytest

from skill_atlas import runtime


def skill(name="review", description="Review code changes."):
    return f"---\nname: {name}\ndescription: {description}\n---\n"


def organization(harness):
    """An organization exercising every listing outcome, in non-canonical creation order."""
    zeta = harness.add_repository("Acme/zeta")
    zeta.write(".claude/skills/review/SKILL.md", skill())
    zeta.write(".agents/skills/review/SKILL.md", skill())
    zeta.write("nested space/SKILL.md", skill("nested", "Nested definition."))
    zeta.write("broken/SKILL.md", "---\nname: [wrong type]\n---")
    alpha = harness.add_repository("Acme/alpha")
    alpha.write("SKILL.md", skill("root", "Root definition."))
    docs = harness.add_repository("Acme/docs")
    docs.write("README.md", "No skills here.")
    harness.add_repository("Acme/empty")
    fork = harness.add_repository("Acme/forked", fork=True)
    fork.write("SKILL.md", skill("forked"))
    archived = harness.add_repository("Acme/retired", archived=True)
    archived.write("SKILL.md", skill("retired"))
    for source in (zeta, alpha, docs, fork, archived):
        source.commit()
    return {"alpha": alpha, "docs": docs, "zeta": zeta}


def assert_clean(harness):
    assert not list(harness.git_temporary.iterdir())


def test_organization_scan_matches_individual_scans_with_minimal_requests(organization_harness):
    harness = organization_harness
    repositories = organization(harness)
    # A small server page size exercises pagination; the client still requests 100.
    harness.page_size = 2
    harness.truncated_repositories = {"Acme/zeta"}

    result = harness.scan_url("https://github.com/ACME/")
    assert result.exit_code == 0, result.output
    assert result.stderr == ""
    assert result.stdout.splitlines() == [
        "Acme — 4 repositories, 4 skills",
        "Acme/alpha — 1 skill",
        "Acme/docs — no skills",
        "Acme/empty — empty",
        "Acme/zeta — 3 skills",
    ]
    organization_rows = harness.rows()
    assert {row["repository_url"] for row in organization_rows} == {
        "https://github.com/acme/alpha",
        "https://github.com/acme/zeta",
    }

    # Listing pages carry snapshots: no per-repository metadata or commit requests.
    assert len(harness.requested("graphql")) == 3
    assert harness.requested("repository") == harness.requested("commit") == []
    assert sorted(harness.requested("tree")) == ["Acme/alpha", "Acme/docs", "Acme/zeta"]
    # The API reader reads one blob per SKILL.md; the truncated repository uses Git instead.
    assert harness.requested("blob") == ["Acme/alpha"]
    assert harness.git_fetches == [repositories["zeta"].snapshot().commit_sha]
    assert_clean(harness)

    harness.database.unlink()
    for source in repositories.values():
        assert harness.scan(source).exit_code == 0
    assert harness.rows() == organization_rows
    assert_clean(harness)


def test_failed_repository_keeps_previous_entries_and_others_are_committed(organization_harness):
    harness = organization_harness
    repositories = organization(harness)
    assert harness.scan(repositories["alpha"]).exit_code == 0
    previous = harness.rows()
    repositories["alpha"].write("SKILL.md", skill("root", "Updated definition."))
    repositories["alpha"].commit()
    harness.failed_trees = {"Acme/alpha"}

    result = harness.scan_url("https://github.com/acme")
    assert result.exit_code == 1
    lines = result.stdout.splitlines()
    assert lines[0] == "Acme — 4 repositories, 3 skills"
    assert lines[1] == "Acme/alpha — failed: GitHub request failed (HTTP 503). Try again later."
    assert lines[2:] == ["Acme/docs — no skills", "Acme/empty — empty", "Acme/zeta — 3 skills"]
    assert result.stderr.strip() == "Error: 1 repository failed."
    rows = harness.rows()
    assert [row for row in rows if row["repository_url"].endswith("/alpha")] == previous
    assert {row["skill_name"] for row in rows if row["repository_url"].endswith("/zeta")} == {
        "nested",
        "review",
    }
    assert_clean(harness)


def test_rate_limit_stops_new_repositories_with_four_parallel_workers(organization_harness):
    harness = organization_harness
    names = ["alpha", "beta", "delta", "gamma", "omega", "zeta"]
    for name in names:
        source = harness.add_repository(f"acme/{name}")
        source.write("SKILL.md", skill(name))
        source.commit()
    harness.add_repository("acme/empty")
    # The first four repositories are in progress together before GitHub limits them.
    in_progress = Barrier(4, timeout=5)

    def rate_limited(full_name):
        try:
            in_progress.wait()
        except BrokenBarrierError:
            pytest.fail("Four repositories were not scanned concurrently")
        return httpx.Response(403, headers={"x-ratelimit-remaining": "0"})

    harness.on_tree = rate_limited
    result = harness.scan_url("https://github.com/acme")
    assert result.exit_code == 1
    limited = (
        "failed: GitHub's rate limit was reached. Retry later, or configure a GitHub credential."
    )
    assert result.stdout.splitlines() == [
        "acme — 7 repositories, 0 skills",
        f"acme/alpha — {limited}",
        f"acme/beta — {limited}",
        f"acme/delta — {limited}",
        "acme/empty — empty",
        f"acme/gamma — {limited}",
        "acme/omega — not scanned",
        "acme/zeta — not scanned",
    ]
    assert result.stderr.strip() == (
        "Error: GitHub's rate limit stopped the scan. 4 repositories failed. "
        "2 repositories were not scanned."
    )
    assert sorted(harness.requested("tree")) == [
        "acme/alpha",
        "acme/beta",
        "acme/delta",
        "acme/gamma",
    ]
    assert harness.rows() == []


def test_ctrl_c_keeps_finished_repositories_and_cleans_up_git(organization_harness):
    harness = organization_harness
    alpha = harness.add_repository("acme/alpha")
    alpha.write("SKILL.md", skill("alpha"))
    alpha.commit()
    zeta = harness.add_repository("acme/zeta")
    zeta.write("SKILL.md", skill("zeta"))
    snapshot = zeta.commit()
    harness.truncated_repositories = {"acme/zeta"}
    interrupted = Event()

    def committed():
        try:
            return bool(harness.rows())
        except sqlite3.Error:
            return False  # The other worker is still initializing the catalog.

    def interrupt(commit):
        # Wait for the other worker's commit, then press Ctrl+C mid-way through the fallback.
        deadline = monotonic() + 5
        while not committed() and monotonic() < deadline:
            sleep(0.01)
        _thread.interrupt_main()
        assert harness.cancellations[0].wait(5)
        interrupted.set()

    harness.on_fetch = interrupt
    result = harness.scan_url("https://github.com/acme")
    assert interrupted.is_set()
    # Typer reports Ctrl+C with the conventional SIGINT status.
    assert result.exit_code == 130
    assert harness.git_fetches == [snapshot.commit_sha]
    assert [row["skill_name"] for row in harness.rows()] == ["alpha"]
    assert_clean(harness)


@pytest.mark.parametrize(
    ("url", "message"),
    [
        ("https://github.com/someone", "someone is a GitHub user account"),
        ("https://github.com/hidden", "hidden was not found or is not visible"),
    ],
)
def test_user_accounts_and_invisible_organizations_fail_clearly(organization_harness, url, message):
    harness = organization_harness
    harness.user_accounts = {"someone"}
    result = harness.scan_url(url)
    assert result.exit_code == 1
    assert result.stdout == ""
    assert message in result.stderr
    assert not harness.database.exists()


def test_organization_scan_requires_a_credential(organization_harness, monkeypatch):
    harness = organization_harness
    monkeypatch.setattr(runtime, "github_token", lambda: None)
    result = harness.scan_url("https://github.com/acme")
    assert result.exit_code == 1
    assert "require a GitHub credential" in result.stderr
    assert harness.requests == []


def test_listing_failure_changes_nothing(organization_harness, monkeypatch):
    harness = organization_harness
    organization(harness)
    monkeypatch.setattr(harness, "graphql", lambda request: {"errors": [{"type": "RATE_LIMITED"}]})
    result = harness.scan_url("https://github.com/acme")
    assert result.exit_code == 1
    assert "rate limit" in result.stderr
    assert harness.requested("tree") == []
    assert not harness.database.exists()


@pytest.mark.parametrize("url", ["https://github.com/", "https://github.com/acme?tab=repositories"])
def test_invalid_organization_urls_are_usage_errors(organization_harness, url):
    result = organization_harness.scan_url(url)
    assert result.exit_code == 2
    assert organization_harness.requests == []


def test_concurrent_workers_initialize_and_write_one_new_catalog(organization_harness):
    """Each worker writes through its own short-lived connection and transaction."""
    harness = organization_harness
    for index in range(8):
        source = harness.add_repository(f"acme/repo-{index}")
        for copy in range(3):
            source.write(f"skills/{copy}/SKILL.md", skill(f"skill-{copy}"))
        source.commit()
    result = harness.scan_url("https://github.com/acme")
    assert result.exit_code == 0, result.output
    with sqlite3.connect(harness.database) as connection:
        counts = dict(
            connection.execute(
                "SELECT repository_url, count(*) FROM skills GROUP BY repository_url"
            ).fetchall()
        )
    assert counts == {f"https://github.com/acme/repo-{index}": 3 for index in range(8)}


def test_cancelled_workers_make_no_further_github_requests(organization_harness):
    from skill_atlas.config import Settings
    from skill_atlas.errors import ScanCancelled

    harness = organization_harness
    source = harness.add_repository("acme/alpha")
    source.write("SKILL.md", skill())
    snapshot = source.commit()
    cancelled = Event()
    cancelled.set()
    with (
        runtime.create_organization_scanner(Settings.from_environment()) as scanner,
        scanner.workers(cancelled) as scan,
        pytest.raises(ScanCancelled),
    ):
        scan(snapshot)
    assert harness.requests == []
    assert harness.rows() == []


def test_terminal_progress_stays_on_standard_error(organization_harness, monkeypatch):
    harness = organization_harness
    source = harness.add_repository("acme/alpha")
    source.write("SKILL.md", skill())
    source.commit()
    # Standard error behaves as a terminal; redirected standard output stays plain.
    monkeypatch.setenv("FORCE_COLOR", "1")
    monkeypatch.delenv("TERM", raising=False)
    result = harness.scan_url("https://github.com/acme")
    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines() == ["acme — 1 repository, 1 skill", "acme/alpha — 1 skill"]
