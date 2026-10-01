from threading import Event
from time import monotonic, sleep

import pytest

from skill_atlas.application.grouping_jobs import GroupingJobs
from skill_atlas.errors import GroupingError


def finished(jobs):
    deadline = monotonic() + 3
    while monotonic() < deadline:
        job = jobs.latest()
        if job.state in {"succeeded", "failed"}:
            return job
        sleep(0.01)
    pytest.fail("Generation did not finish")


def test_one_worker_deduplicates_generation_and_allows_regeneration():
    gate, started = Event(), Event()
    seen = []

    def generate():
        seen.append(True)
        started.set()
        assert gate.wait(3)
        return ()

    jobs = GroupingJobs(generate)
    try:
        assert jobs.latest() is None
        first = jobs.submit()
        assert started.wait(3)
        assert jobs.submit().id == first.id
        assert len(seen) == 1
        gate.set()
        assert finished(jobs).state == "succeeded"
        assert jobs.submit().id != first.id
        assert finished(jobs).state == "succeeded"
        assert len(seen) == 2
    finally:
        gate.set()
        jobs.close()
    with pytest.raises(GroupingError, match="stopping"):
        jobs.submit()


@pytest.mark.parametrize(
    "error,message",
    [(GroupingError("Useful error"), "Useful error"), (RuntimeError("secret"), "unexpectedly")],
)
def test_failures_remain_retryable_and_unexpected_errors_are_sanitized(error, message):
    def fail():
        raise error

    jobs = GroupingJobs(fail)
    try:
        first = jobs.submit()
        result = finished(jobs)
        assert result.state == "failed" and message in result.error
        assert "secret" not in result.error
        assert jobs.submit().id != first.id
        finished(jobs)
    finally:
        jobs.close()
