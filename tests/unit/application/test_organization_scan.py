from contextlib import contextmanager
from threading import Event, Lock, Timer
from time import sleep

import pytest

from skill_atlas.application.organization_scan import (
    OrganizationProgress,
    OrganizationScanner,
    RepositoryOutcome,
)
from skill_atlas.errors import RateLimitError, RepositoryError, ScanCancelled
from skill_atlas.models import (
    Organization,
    OrganizationListing,
    OrganizationRepository,
    Repository,
    ScanResult,
    Skill,
    Snapshot,
)

ORGANIZATION = Organization("Acme")


def listed(name, *, fork=False, archived=False, empty=False):
    repository = Repository("Acme", name)
    snapshot = None if empty else Snapshot(repository, "a" * 40, "b" * 40)
    return OrganizationRepository(repository, fork, archived, snapshot)


class Reader:
    def __init__(self, *repositories):
        self.listing = OrganizationListing(ORGANIZATION, repositories)
        self.calls = 0

    def list_repositories(self, organization):
        self.calls += 1
        return self.listing


class Workers:
    """Fake workers that record lifetimes, concurrency, and scanned snapshots."""

    def __init__(self, scan=None):
        self.scan = scan or (lambda snapshot: result(snapshot, 1))
        self.lock = Lock()
        self.active = 0
        self.peak = 0
        self.opened = 0
        self.closed = 0
        self.scanned = []

    @contextmanager
    def __call__(self, cancelled):
        with self.lock:
            self.opened += 1
        try:
            yield self.run
        finally:
            with self.lock:
                self.closed += 1

    def run(self, snapshot):
        with self.lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
            self.scanned.append(snapshot.repository.name)
        try:
            return self.scan(snapshot)
        finally:
            with self.lock:
                self.active -= 1


def result(snapshot, count):
    skills = tuple(
        Skill(snapshot.repository, f"{index}/SKILL.md", "name", "description", snapshot.commit_sha)
        for index in range(count)
    )
    return ScanResult(snapshot.repository, snapshot.commit_sha, skills)


def test_eligible_repositories_are_scanned_in_canonical_order_with_outcomes():
    def scan(snapshot):
        if snapshot.repository.name == "broken":
            raise RepositoryError("Permission denied")
        if snapshot.repository.name == "surprise":
            raise RuntimeError("secret detail")
        return result(snapshot, 0 if snapshot.repository.name == "docs" else 2)

    reader = Reader(
        listed("zeta"),
        listed("docs"),
        listed("fork", fork=True),
        listed("old", archived=True),
        listed("new", empty=True),
        listed("broken"),
        listed("surprise"),
    )
    workers = Workers(scan)
    updates = []
    scanned = OrganizationScanner(reader, workers).scan(ORGANIZATION, progress=updates.append)

    assert [(outcome.repository.name, outcome.state) for outcome in scanned.repositories] == [
        ("broken", "failed"),
        ("docs", "succeeded"),
        ("new", "empty"),
        ("surprise", "failed"),
        ("zeta", "succeeded"),
    ]
    assert scanned.repositories[0].error == "Permission denied"
    assert scanned.repositories[3].error == "Scan failed unexpectedly. Try again."
    assert scanned.skill_count == 2
    assert not scanned.succeeded and not scanned.rate_limited
    assert scanned.problem == "2 repositories failed."
    assert sorted(workers.scanned) == ["broken", "docs", "surprise", "zeta"]
    assert updates[0] == OrganizationProgress(5, 1)
    assert updates[-1] == OrganizationProgress(5, 5)
    assert [update.finished for update in updates] == [1, 2, 3, 4, 5]
    assert workers.opened == workers.closed == 4


def test_at_most_four_workers_run_concurrently():
    def scan(snapshot):
        sleep(0.02)
        return result(snapshot, 1)

    workers = Workers(scan)
    reader = Reader(*(listed(f"repo-{index:02}") for index in range(12)))
    scanned = OrganizationScanner(reader, workers).scan(ORGANIZATION)
    assert scanned.succeeded and scanned.problem is None
    assert scanned.skill_count == 12
    assert workers.peak == 4
    assert workers.opened == workers.closed == 4


def test_small_organizations_start_only_needed_workers():
    workers = Workers()
    scanned = OrganizationScanner(
        Reader(listed("only"), listed("empty", empty=True)), workers
    ).scan(ORGANIZATION)
    assert scanned.succeeded
    assert workers.opened == 1
    empty = OrganizationScanner(Reader(listed("fork", fork=True)), workers).scan(ORGANIZATION)
    assert empty.repositories == () and empty.succeeded and empty.skill_count == 0
    assert workers.opened == 1


def test_rate_limit_stops_new_repositories_while_in_progress_scans_finish():
    limited, finishing = Event(), Event()

    def scan(snapshot):
        if snapshot.repository.name == "a-slow":
            assert limited.wait(3)
            finishing.set()
            return result(snapshot, 1)
        if snapshot.repository.name == "b-limited":
            limited.set()
            raise RateLimitError("GitHub's rate limit was reached.")
        return result(snapshot, 1)

    reader = Reader(listed("a-slow"), listed("b-limited"), listed("c-later"), listed("d-later"))
    scanned = OrganizationScanner(reader, Workers(scan), max_workers=2).scan(ORGANIZATION)
    assert finishing.is_set()
    assert [outcome.state for outcome in scanned.repositories] == [
        "succeeded",
        "failed",
        "not_scanned",
        "not_scanned",
    ]
    assert scanned.rate_limited
    assert scanned.problem == (
        "GitHub's rate limit stopped the scan. 1 repository failed. "
        "2 repositories were not scanned."
    )


def test_listing_failures_propagate_before_any_worker_starts():
    class FailingReader:
        def list_repositories(self, organization):
            raise RepositoryError("GitHub organization acme was not found")

    workers = Workers()
    with pytest.raises(RepositoryError, match="not found"):
        OrganizationScanner(FailingReader(), workers).scan(ORGANIZATION)
    assert workers.opened == 0


def test_interrupt_cancels_in_progress_workers_and_releases_their_resources():
    signals, closed = [], []
    stopped = Event()
    reports = iter([None])  # Progress is first reported before workers start.

    def interrupting(update):
        # Ctrl+C after one repository finished while another is still running.
        if next(reports, "interrupt") == "interrupt":
            raise KeyboardInterrupt

    @contextmanager
    def workers(cancelled):
        signals.append(cancelled)

        def scan(snapshot):
            if snapshot.repository.name == "one":
                return result(snapshot, 1)
            assert cancelled.wait(3), "The in-progress worker was not cancelled"
            stopped.set()
            raise ScanCancelled("stopped")

        try:
            yield scan
        finally:
            closed.append("closed")

    reader = Reader(listed("one"), listed("two"))
    caller = Event()
    with pytest.raises(KeyboardInterrupt):
        OrganizationScanner(reader, workers).scan(
            ORGANIZATION, progress=interrupting, cancelled=caller
        )
    assert stopped.is_set()
    assert closed == ["closed", "closed"]
    assert all(cancelled.is_set() for cancelled in signals)
    # The scanner stops its own workers; the caller's signal stays reusable.
    assert not caller.is_set()


def test_caller_cancellation_reaches_in_progress_workers():
    caller, waiting = Event(), Event()
    scanned = []

    @contextmanager
    def workers(cancelled):
        def scan(snapshot):
            scanned.append(snapshot.repository.name)
            waiting.set()
            # Workers observe the scanner's own signal, which follows the caller's.
            assert cancelled.wait(3), "The caller's cancellation did not reach the worker"
            raise ScanCancelled("stopped")

        yield scan

    timer = Timer(0.1, lambda: waiting.wait(3) and caller.set())
    timer.start()
    try:
        with pytest.raises(ScanCancelled, match="stopped before it finished"):
            OrganizationScanner(
                Reader(listed("one"), listed("two"), listed("three")), workers, max_workers=1
            ).scan(ORGANIZATION, cancelled=caller)
    finally:
        timer.cancel()
    assert scanned == ["one"]


def test_already_cancelled_scans_start_no_repositories():
    caller = Event()
    caller.set()
    workers = Workers()
    with pytest.raises(ScanCancelled):
        OrganizationScanner(Reader(listed("one")), workers).scan(ORGANIZATION, cancelled=caller)
    assert workers.scanned == []


def test_worker_setup_failure_leaves_repositories_not_scanned():
    @contextmanager
    def failing(cancelled):
        raise OSError("no resources")
        yield

    scanned = OrganizationScanner(Reader(listed("one")), failing).scan(ORGANIZATION)
    assert scanned.repositories == (RepositoryOutcome(Repository("Acme", "one"), "not_scanned"),)
    assert scanned.problem == "1 repository was not scanned."
