from threading import Event
from time import monotonic, sleep

import pytest

from skill_atlas.application.grouping_jobs import GroupingJobs
from skill_atlas.errors import GroupingError
from skill_atlas.grouping import Perspective


def finished(jobs, perspective):
    deadline = monotonic() + 3
    while monotonic() < deadline:
        job = jobs.latest(perspective)
        if job.state in {"succeeded", "failed"}:
            return job
        sleep(0.01)
    pytest.fail("Generation did not finish")


def test_one_worker_deduplicates_and_queues_other_perspective():
    gate, started = Event(), Event()
    seen = []

    def generate(p):
        seen.append(p)
        started.set()
        assert gate.wait(3)

    jobs = GroupingJobs(generate)
    try:
        first = jobs.submit(Perspective.TOPICS)
        assert started.wait(3)
        assert jobs.submit(Perspective.TOPICS).id == first.id
        second = jobs.submit(Perspective.CAPABILITIES)
        assert second.state == "queued"
        assert seen == [Perspective.TOPICS]
        gate.set()
        assert finished(jobs, Perspective.CAPABILITIES).state == "succeeded"
        assert seen == [Perspective.TOPICS, Perspective.CAPABILITIES]
    finally:
        gate.set()
        jobs.close()
    with pytest.raises(GroupingError, match="stopping"):
        jobs.submit(Perspective.TOPICS)


@pytest.mark.parametrize(
    "error,message",
    [(GroupingError("Useful error"), "Useful error"), (RuntimeError("secret"), "unexpectedly")],
)
def test_failures_remain_retryable_and_unexpected_errors_are_sanitized(error, message):
    def fail(_):
        raise error

    jobs = GroupingJobs(fail)
    try:
        first = jobs.submit(Perspective.TOPICS)
        result = finished(jobs, Perspective.TOPICS)
        assert result.state == "failed" and message in result.error
        assert "secret" not in result.error
        assert jobs.submit(Perspective.TOPICS).id != first.id
        finished(jobs, Perspective.TOPICS)
    finally:
        jobs.close()
