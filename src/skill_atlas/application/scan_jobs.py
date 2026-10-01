"""One bounded, process-local scan worker. The catalog remains the durable state."""

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, replace
from threading import Condition, Event, Thread
from typing import Literal
from uuid import uuid4

from skill_atlas.application.organization_scan import (
    OrganizationProgress,
    OrganizationScanResult,
    RepositoryOutcome,
)
from skill_atlas.errors import AtlasError
from skill_atlas.models import Organization, Repository, ScanResult

OrganizationScan = Callable[
    [Organization, Callable[[OrganizationProgress], None], Event], OrganizationScanResult
]


class QueueFull(AtlasError):
    pass


@dataclass(frozen=True)
class ScanJob:
    id: str
    target: Repository | Organization
    state: Literal["queued", "running", "succeeded", "failed"] = "queued"
    skill_count: int | None = None
    commit_sha: str | None = None
    error: str | None = None
    # Organization jobs report progress and per-repository failures.
    repository_count: int | None = None
    finished_count: int = 0
    failures: tuple[RepositoryOutcome, ...] = ()

    @property
    def organization(self) -> bool:
        return isinstance(self.target, Organization)


class ScanJobs:
    def __init__(
        self,
        scan: Callable[[Repository], ScanResult],
        scan_organization: OrganizationScan | None = None,
        *,
        capacity: int = 16,
        retention: int = 64,
    ) -> None:
        self.scan = scan
        self.scan_organization = scan_organization
        self.capacity = capacity
        self.retention = retention
        self._condition = Condition()
        self._queue: deque[str] = deque()
        self._completed: deque[str] = deque()
        self._jobs: dict[str, ScanJob] = {}
        self._closing = False
        # Each organization job gets its own signal, so one job's stop never affects another.
        self._active_cancellation: Event | None = None
        self._thread = Thread(target=self._work, name="skill-atlas-scans")

    def start(self) -> None:
        self._thread.start()

    def submit(self, target: Repository | Organization) -> ScanJob:
        with self._condition:
            if self._closing:
                raise QueueFull("The server is stopping. Start it again to scan.")
            for job in self._jobs.values():
                if job.target.url == target.url and job.state in ("queued", "running"):
                    return job
            if len(self._queue) >= self.capacity:
                raise QueueFull("The scan queue is full. Wait for a scan to finish and retry.")
            job = ScanJob(uuid4().hex, target)
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
            if self._active_cancellation is not None:
                self._active_cancellation.set()
            while self._queue:
                del self._jobs[self._queue.popleft()]
            self._condition.notify_all()
        if self._thread.is_alive():
            self._thread.join()

    def _progress(self, job_id: str) -> Callable[[OrganizationProgress], None]:
        def update(progress: OrganizationProgress) -> None:
            with self._condition:
                self._jobs[job_id] = replace(
                    self._jobs[job_id],
                    repository_count=progress.total,
                    finished_count=progress.finished,
                )

        return update

    def _run(self, job: ScanJob) -> ScanJob:
        if isinstance(job.target, Repository):
            result = self.scan(job.target)
            return replace(
                job,
                state="succeeded",
                target=result.repository,
                skill_count=len(result.skills),
                commit_sha=result.commit_sha,
            )
        if self.scan_organization is None:
            raise AtlasError("Organization scans are not available.")
        cancellation = Event()
        with self._condition:
            # Shutdown may have begun after this job started running.
            if self._closing:
                cancellation.set()
            self._active_cancellation = cancellation
        try:
            outcome = self.scan_organization(job.target, self._progress(job.id), cancellation)
        finally:
            with self._condition:
                self._active_cancellation = None
        # Progress updates replaced the registry entry while the scan ran.
        with self._condition:
            job = self._jobs[job.id]
        return replace(
            job,
            state="succeeded" if outcome.succeeded else "failed",
            target=outcome.organization,
            skill_count=outcome.skill_count,
            repository_count=len(outcome.repositories),
            finished_count=len(outcome.repositories),
            error=outcome.problem,
            failures=outcome.failures,
        )

    def _work(self) -> None:
        while True:
            with self._condition:
                self._condition.wait_for(lambda: bool(self._queue) or self._closing)
                if self._closing:
                    return
                job = replace(self._jobs[self._queue.popleft()], state="running")
                self._jobs[job.id] = job
            try:
                job = self._run(job)
            except Exception as error:
                message = (
                    str(error)
                    if isinstance(error, AtlasError)
                    else "Scan failed unexpectedly. Try again."
                )
                with self._condition:
                    job = replace(self._jobs[job.id], state="failed", error=message)
            with self._condition:
                self._jobs[job.id] = job
                self._completed.append(job.id)
                while len(self._completed) > self.retention:
                    del self._jobs[self._completed.popleft()]
