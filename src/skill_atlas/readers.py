"""Reader selection policy, independent of HTTP and Git implementations."""

from collections.abc import Iterable

from skill_atlas.errors import IncompleteListingError
from skill_atlas.models import Repository, SkillFile, Snapshot
from skill_atlas.ports import RepositoryReader, SnapshotReader


class FallbackReader:
    def __init__(self, primary: RepositoryReader, fallback: SnapshotReader) -> None:
        self.primary = primary
        self.fallback = fallback
        self._fallback_snapshots: set[Snapshot] = set()

    def resolve(self, repository: Repository) -> Snapshot:
        return self.primary.resolve(repository)

    def skill_files(self, snapshot: Snapshot) -> Iterable[SkillFile]:
        if snapshot not in self._fallback_snapshots:
            try:
                # Fully enumerate before returning anything, so a truncated
                # listing cannot leak partial or duplicate entries to the scanner.
                return tuple(self.primary.skill_files(snapshot))
            except IncompleteListingError:
                self._fallback_snapshots.add(snapshot)
        return self.fallback.skill_files(snapshot)

    def read_file(self, snapshot: Snapshot, file: SkillFile) -> bytes:
        reader = self.fallback if snapshot in self._fallback_snapshots else self.primary
        return reader.read_file(snapshot, file)
