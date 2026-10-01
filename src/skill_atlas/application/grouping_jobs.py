"""One deduplicated generation job publishes both perspectives."""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from threading import Lock
from typing import Literal
from uuid import uuid4

from skill_atlas.errors import AtlasError, GroupingError
from skill_atlas.grouping import Grouping


@dataclass(frozen=True)
class GroupingJob:
    id: str
    state: Literal["queued", "running", "succeeded", "failed"] = "queued"
    error: str = ""


class GroupingJobs:
    def __init__(self, generate: Callable[[], tuple[Grouping, ...]]) -> None:
        self.generate = generate
        self._lock = Lock()
        self._job: GroupingJob | None = None
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="skill-atlas-groups")
        self._closed = False

    def latest(self) -> GroupingJob | None:
        with self._lock:
            return self._job

    def submit(self) -> GroupingJob:
        with self._lock:
            if self._closed:
                raise GroupingError("The server is stopping. Restart it to generate groups.")
            job = self._job
            if job and job.state in {"queued", "running"}:
                return job
            job = GroupingJob(uuid4().hex)
            self._job = job
            self._executor.submit(self._run, job)
            return job

    def close(self) -> None:
        with self._lock:
            self._closed = True
        self._executor.shutdown(wait=True, cancel_futures=True)
        with self._lock:
            if self._job and self._job.state == "queued":
                self._job = None

    def _run(self, job: GroupingJob) -> None:
        with self._lock:
            self._job = replace(job, state="running")
        try:
            self.generate()
            result = replace(job, state="succeeded")
        except Exception as error:
            message = (
                str(error)
                if isinstance(error, AtlasError)
                else "Generation failed unexpectedly. Retry generation."
            )
            result = replace(job, state="failed", error=message)
        with self._lock:
            self._job = result
