"""Organization scan use case: list once, then scan repositories with bounded parallelism."""

from collections import deque
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from queue import Empty, Queue
from threading import Event, Lock, Thread
from typing import Literal

from skill_atlas.errors import AtlasError, RateLimitError, ScanCancelled
from skill_atlas.models import Organization, Repository, ScanResult, Snapshot
from skill_atlas.ports import OrganizationReader

MAX_WORKERS = 4

SnapshotScan = Callable[[Snapshot], ScanResult]
# A worker receives the scan's cancellation signal and owns its resources for its lifetime.
WorkerFactory = Callable[[Event], AbstractContextManager[SnapshotScan]]


@dataclass(frozen=True)
class RepositoryOutcome:
    repository: Repository
    state: Literal["succeeded", "empty", "failed", "not_scanned"]
    skill_count: int = 0
    error: str | None = None


@dataclass(frozen=True)
class OrganizationProgress:
    total: int
    finished: int


@dataclass(frozen=True)
class OrganizationScanResult:
    organization: Organization
    repositories: tuple[RepositoryOutcome, ...]
    rate_limited: bool = False

    @property
    def skill_count(self) -> int:
        return sum(outcome.skill_count for outcome in self.repositories)

    @property
    def failures(self) -> tuple[RepositoryOutcome, ...]:
        return tuple(outcome for outcome in self.repositories if outcome.state == "failed")

    @property
    def not_scanned(self) -> tuple[RepositoryOutcome, ...]:
        return tuple(outcome for outcome in self.repositories if outcome.state == "not_scanned")

    @property
    def succeeded(self) -> bool:
        return all(outcome.state in ("succeeded", "empty") for outcome in self.repositories)

    @property
    def problem(self) -> str | None:
        """One shared explanation of an unsuccessful outcome for every interface."""
        sentences = ["GitHub's rate limit stopped the scan."] if self.rate_limited else []
        if failed := len(self.failures):
            sentences.append(f"{_repositories(failed)} failed.")
        if skipped := len(self.not_scanned):
            sentences.append(
                f"{_repositories(skipped)} {'was' if skipped == 1 else 'were'} not scanned."
            )
        return " ".join(sentences) or None


def _repositories(count: int) -> str:
    return f"{count} {'repository' if count == 1 else 'repositories'}"


class OrganizationScanner:
    def __init__(
        self, reader: OrganizationReader, workers: WorkerFactory, *, max_workers: int = MAX_WORKERS
    ) -> None:
        self.reader = reader
        self.workers = workers
        self.max_workers = max_workers

    def scan(
        self,
        organization: Organization,
        *,
        progress: Callable[[OrganizationProgress], None] | None = None,
        cancelled: Event | None = None,
    ) -> OrganizationScanResult:
        """Scan eligible repositories; each one is committed independently."""
        cancelled = Event() if cancelled is None else cancelled
        # Listing failures stop the scan before any repository is changed.
        listing = self.reader.list_repositories(organization)
        eligible = sorted(
            (item for item in listing.repositories if not item.fork and not item.archived),
            key=lambda item: item.repository.url,
        )
        outcomes = {
            item.repository.url: RepositoryOutcome(item.repository, "empty")
            for item in eligible
            if item.snapshot is None
        }
        pending = deque(item.snapshot for item in eligible if item.snapshot is not None)
        report = progress or (lambda update: None)
        report(OrganizationProgress(len(eligible), len(outcomes)))

        lock = Lock()
        halted = Event()
        finished: Queue[RepositoryOutcome | None] = Queue()

        def next_snapshot() -> Snapshot | None:
            with lock:
                if halted.is_set() or cancelled.is_set() or not pending:
                    return None
                return pending.popleft()

        def work() -> None:
            try:
                with self.workers(cancelled) as scan_snapshot:
                    while (snapshot := next_snapshot()) is not None:
                        finished.put(self._scan_one(scan_snapshot, snapshot, halted))
            except Exception:
                # Repositories this worker never started are reported as not scanned.
                pass
            finally:
                finished.put(None)

        threads = [
            Thread(target=work, name=f"skill-atlas-organization-{index}")
            for index in range(min(self.max_workers, len(pending)))
        ]
        try:
            for thread in threads:
                thread.start()
            active = len(threads)
            while active:
                try:
                    # A bounded wait keeps Ctrl+C responsive on every platform.
                    outcome = finished.get(timeout=0.2)
                except Empty:
                    continue
                if outcome is None:
                    active -= 1
                    continue
                outcomes[outcome.repository.url] = outcome
                report(OrganizationProgress(len(eligible), len(outcomes)))
        except BaseException:
            cancelled.set()
            raise
        finally:
            # Workers unwind their HTTP and Git resources before the scan returns or raises.
            for thread in threads:
                if thread.is_alive():
                    thread.join()

        if cancelled.is_set():
            raise ScanCancelled("The organization scan was stopped before it finished.")
        for item in eligible:
            outcomes.setdefault(
                item.repository.url, RepositoryOutcome(item.repository, "not_scanned")
            )
        return OrganizationScanResult(
            listing.organization,
            tuple(outcomes[item.repository.url] for item in eligible),
            rate_limited=halted.is_set(),
        )

    @staticmethod
    def _scan_one(scan: SnapshotScan, snapshot: Snapshot, halted: Event) -> RepositoryOutcome:
        try:
            result = scan(snapshot)
        except RateLimitError as error:
            # Stop starting repositories; scans already in progress may still finish.
            halted.set()
            return RepositoryOutcome(snapshot.repository, "failed", error=str(error))
        except AtlasError as error:
            return RepositoryOutcome(snapshot.repository, "failed", error=str(error))
        except Exception:
            return RepositoryOutcome(
                snapshot.repository, "failed", error="Scan failed unexpectedly. Try again."
            )
        return RepositoryOutcome(snapshot.repository, "succeeded", len(result.skills))
