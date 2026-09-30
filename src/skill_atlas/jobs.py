"""One bounded, process-local scan worker. The catalog remains the durable state."""

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, replace
from threading import Condition, Thread
from typing import Literal
from uuid import uuid4

from skill_atlas.errors import AtlasError
from skill_atlas.models import Repository, ScanResult


class QueueFull(AtlasError):
    pass


@dataclass(frozen=True)
class ScanJob:
    id: str
    repository: Repository
    state: Literal["queued", "running", "succeeded", "failed"] = "queued"
    skill_count: int | None = None
    commit_sha: str | None = None
    error: str | None = None


class ScanJobs:
    def __init__(
        self, scan: Callable[[Repository], ScanResult], *, capacity: int = 16, retention: int = 64
    ) -> None:
        self.scan = scan
        self.capacity = capacity
        self.retention = retention
        self._condition = Condition()
        self._queue: deque[str] = deque()
        self._completed: deque[str] = deque()
        self._jobs: dict[str, ScanJob] = {}
        self._closing = False
        self._thread = Thread(target=self._work, name="skill-atlas-scans")

    def start(self) -> None:
        self._thread.start()

    def submit(self, repository: Repository) -> ScanJob:
        with self._condition:
            if self._closing:
                raise QueueFull("The server is stopping. Start it again to scan.")
            for job in self._jobs.values():
                if job.repository.url == repository.url and job.state in ("queued", "running"):
                    return job
            if len(self._queue) >= self.capacity:
                raise QueueFull("The scan queue is full. Wait for a scan to finish and retry.")
            job = ScanJob(uuid4().hex, repository)
            self._jobs[job.id] = job
            self._queue.append(job.id)
            self._condition.notify()
            return job

    def get(self, job_id: str) -> ScanJob | None:
        with self._condition:
            return self._jobs.get(job_id)

    def recent(self) -> tuple[ScanJob, ...]:
        with self._condition:
            return tuple(reversed(tuple(self._jobs.values())))

    def close(self) -> None:
        with self._condition:
            self._closing = True
            while self._queue:
                del self._jobs[self._queue.popleft()]
            self._condition.notify_all()
        if self._thread.is_alive():
            self._thread.join()

    def _work(self) -> None:
        while True:
            with self._condition:
                self._condition.wait_for(lambda: bool(self._queue) or self._closing)
                if self._closing:
                    return
                job = replace(self._jobs[self._queue.popleft()], state="running")
                self._jobs[job.id] = job
            try:
                result = self.scan(job.repository)
                job = replace(
                    job,
                    state="succeeded",
                    repository=result.repository,
                    skill_count=len(result.skills),
                    commit_sha=result.commit_sha,
                )
            except Exception as error:
                message = (
                    str(error)
                    if isinstance(error, AtlasError)
                    else "Scan failed unexpectedly. Try again."
                )
                job = replace(job, state="failed", error=message)
            with self._condition:
                self._jobs[job.id] = job
                self._completed.append(job.id)
                while len(self._completed) > self.retention:
                    del self._jobs[self._completed.popleft()]
