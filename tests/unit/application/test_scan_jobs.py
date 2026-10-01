from dataclasses import replace
from threading import Event
from time import monotonic, sleep

import pytest

from skill_atlas.application.scan_jobs import QueueFull, ScanJobs
from skill_atlas.errors import RepositoryError
from skill_atlas.models import Organization, Repository


def await_state(jobs, job_id, state):
    deadline = monotonic() + 3
    while monotonic() < deadline:
        job = jobs.get(job_id)
        if job and job.state == state:
            return job
        sleep(0.005)
    pytest.fail(f"Job did not reach {state}: {jobs.get(job_id)}")


def test_job_worker_deduplicates_limits_and_cleans_up(scan_result):
    entered, release = Event(), Event()

    def scan(repository):
        entered.set()
        assert release.wait(3)
        return replace(scan_result, repository=repository)

    jobs = ScanJobs(scan, capacity=1, retention=1)
    jobs.start()
    try:
        first = jobs.submit(scan_result.repository)
        assert entered.wait(3)
        assert jobs.get(first.id).state == "running"
        assert jobs.submit(Repository("acme", "skills")).id == first.id
        second = jobs.submit(Repository("acme", "second"))
        assert second.state == "queued"
        with pytest.raises(QueueFull, match="full"):
            jobs.submit(Repository("acme", "third"))
        release.set()
        assert await_state(jobs, second.id, "succeeded").skill_count == 2
        assert jobs.get(first.id) is None
        assert len(jobs.recent()) == 1
    finally:
        release.set()
        jobs.close()
    with pytest.raises(QueueFull, match="stopping"):
        jobs.submit(scan_result.repository)


def test_worker_recovers_from_expected_and_unexpected_failures(scan_result):
    outcomes = iter([RepositoryError("Permission denied"), RuntimeError("secret"), scan_result])

    def scan(repository):
        result = next(outcomes)
        if isinstance(result, Exception):
            raise result
        return result

    jobs = ScanJobs(scan)
    jobs.start()
    try:
        first = jobs.submit(scan_result.repository)
        assert await_state(jobs, first.id, "failed").error == "Permission denied"
        second = jobs.submit(scan_result.repository)
        assert "secret" not in await_state(jobs, second.id, "failed").error
        third = jobs.submit(scan_result.repository)
        assert await_state(jobs, third.id, "succeeded").commit_sha == scan_result.commit_sha
    finally:
        jobs.close()


def test_shutdown_discards_queued_jobs(scan_result):
    jobs = ScanJobs(lambda repository: scan_result)
    job = jobs.submit(scan_result.repository)
    jobs.close()
    assert jobs.get(job.id) is None


def organization_result(*outcomes, rate_limited=False):
    from skill_atlas.application.organization_scan import OrganizationScanResult

    return OrganizationScanResult(Organization("Acme"), outcomes, rate_limited)


def test_organization_jobs_report_progress_deduplicate_and_succeed(scan_result):
    from skill_atlas.application.organization_scan import OrganizationProgress, RepositoryOutcome

    listed, release = Event(), Event()

    def scan_organization(organization, progress, cancelled):
        assert organization == Organization("acme")
        progress(OrganizationProgress(3, 1))
        listed.set()
        assert release.wait(3)
        return organization_result(
            RepositoryOutcome(Repository("Acme", "a"), "succeeded", 2),
            RepositoryOutcome(Repository("Acme", "b"), "empty"),
            RepositoryOutcome(Repository("Acme", "c"), "succeeded", 0),
        )

    jobs = ScanJobs(lambda repository: scan_result, scan_organization)
    jobs.start()
    try:
        job = jobs.submit(Organization("acme"))
        assert job.organization
        assert listed.wait(3)
        running = jobs.get(job.id)
        assert (running.state, running.finished_count, running.repository_count) == (
            "running",
            1,
            3,
        )
        assert jobs.submit(Organization("ACME")).id == job.id
        # An organization and one of its repositories are distinct jobs.
        assert jobs.submit(Repository("acme", "a")).id != job.id
        release.set()
        done = await_state(jobs, job.id, "succeeded")
        assert done.target == Organization("Acme")
        assert (done.repository_count, done.finished_count, done.skill_count) == (3, 3, 2)
        assert done.error is None and done.failures == ()
    finally:
        release.set()
        jobs.close()


def test_organization_jobs_fail_with_their_failed_repositories(scan_result):
    from skill_atlas.application.organization_scan import RepositoryOutcome

    failed = RepositoryOutcome(Repository("Acme", "b"), "failed", error="Permission denied")
    outcomes = iter(
        [
            organization_result(
                RepositoryOutcome(Repository("Acme", "a"), "succeeded", 1),
                failed,
                RepositoryOutcome(Repository("Acme", "c"), "not_scanned"),
                rate_limited=True,
            ),
            RepositoryError("GitHub organization acme was not found"),
        ]
    )

    def scan_organization(organization, progress, cancelled):
        outcome = next(outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    jobs = ScanJobs(lambda repository: scan_result, scan_organization)
    jobs.start()
    try:
        first = await_state(jobs, jobs.submit(Organization("acme")).id, "failed")
        assert first.failures == (failed,)
        assert first.skill_count == 1
        assert first.error == (
            "GitHub's rate limit stopped the scan. 1 repository failed. "
            "1 repository was not scanned."
        )
        listing = await_state(jobs, jobs.submit(Organization("acme")).id, "failed")
        assert listing.error == "GitHub organization acme was not found"
        assert listing.repository_count is None and listing.failures == ()
    finally:
        jobs.close()


def test_shutdown_cancels_an_active_organization_scan(scan_result):
    from skill_atlas.errors import ScanCancelled

    started = Event()

    def scan_organization(organization, progress, cancelled):
        started.set()
        assert cancelled.wait(3)
        raise ScanCancelled("stopped")

    jobs = ScanJobs(lambda repository: scan_result, scan_organization)
    jobs.start()
    job = jobs.submit(Organization("acme"))
    assert started.wait(3)
    jobs.close()
    assert jobs.get(job.id).state == "failed"


def test_organization_jobs_need_an_organization_scanner(scan_result):
    jobs = ScanJobs(lambda repository: scan_result)
    jobs.start()
    try:
        job = await_state(jobs, jobs.submit(Organization("acme")).id, "failed")
        assert job.error == "Organization scans are not available."
    finally:
        jobs.close()


def test_a_failed_organization_scan_does_not_cancel_later_jobs(scan_result):
    from contextlib import contextmanager

    from skill_atlas.application.organization_scan import OrganizationScanner
    from skill_atlas.models import OrganizationListing, OrganizationRepository, Snapshot

    repository = Repository("Acme", "skills")
    snapshot = Snapshot(repository, "a" * 40, "b" * 40)

    class Reader:
        def list_repositories(self, organization):
            listed = OrganizationRepository(repository, False, False, snapshot)
            return OrganizationListing(Organization("Acme"), (listed,))

    @contextmanager
    def workers(cancelled):
        def scan(snapshot):
            # Later scans would stop here if an earlier job left its signal set.
            if cancelled.is_set():
                raise AssertionError("The worker started already cancelled")
            return replace(scan_result, repository=repository)

        yield scan

    failures = iter([True, False])

    def scan_organization(organization, progress, cancelled):
        fail = next(failures)

        def report(update):
            # The first job fails inside the scan loop, after its workers started.
            if fail and update.finished:
                raise RuntimeError("progress failed")
            progress(update)

        return OrganizationScanner(Reader(), workers).scan(
            organization, progress=report, cancelled=cancelled
        )

    jobs = ScanJobs(lambda repository: scan_result, scan_organization)
    jobs.start()
    try:
        failed = await_state(jobs, jobs.submit(Organization("acme")).id, "failed")
        assert failed.error == "Scan failed unexpectedly. Try again."
        later = await_state(jobs, jobs.submit(Organization("acme")).id, "succeeded")
        assert later.skill_count == 2
    finally:
        jobs.close()
