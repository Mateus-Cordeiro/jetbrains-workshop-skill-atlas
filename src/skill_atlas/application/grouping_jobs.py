"""One generation worker; at most one active job per grouping perspective."""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from threading import Lock
from typing import Literal
from uuid import uuid4

from skill_atlas.errors import AtlasError, GroupingError
from skill_atlas.grouping import Grouping, Perspective


@dataclass(frozen=True)
class GroupingJob:
    id: str
    perspective: Perspective
    state: Literal["queued", "running", "succeeded", "failed"] = "queued"
    error: str = ""


class GroupingJobs:
    def __init__(self, generate: Callable[[Perspective], Grouping]) -> None:
        self.generate = generate
        self._lock = Lock()
        self._jobs: dict[Perspective, GroupingJob] = {}
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="skill-atlas-groups")
        self._closed = False

    def latest(self, perspective: Perspective) -> GroupingJob | None:
        with self._lock:
            return self._jobs.get(perspective)

    def submit(self, perspective: Perspective) -> GroupingJob:
        with self._lock:
            if self._closed:
                raise GroupingError("The server is stopping. Restart it to generate groups.")
            job = self._jobs.get(perspective)
            if job and job.state in {"queued", "running"}:
                return job
            job = GroupingJob(uuid4().hex, perspective)
            self._jobs[perspective] = job
            self._executor.submit(self._run, job)
            return job

    def close(self) -> None:
        with self._lock:
            self._closed = True
        self._executor.shutdown(wait=True, cancel_futures=True)
        with self._lock:
            self._jobs = {p: j for p, j in self._jobs.items() if j.state != "queued"}

    def _run(self, job: GroupingJob) -> None:
        with self._lock:
            self._jobs[job.perspective] = replace(job, state="running")
        try:
            self.generate(job.perspective)
            result = replace(job, state="succeeded")
        except Exception as error:
            message = (
                str(error)
                if isinstance(error, AtlasError)
                else "Generation failed unexpectedly. Retry generation."
            )
            result = replace(job, state="failed", error=message)
        with self._lock:
            self._jobs[job.perspective] = result
