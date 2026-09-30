import pytest

from skill_atlas.errors import IncompleteListingError, RepositoryError
from skill_atlas.models import SkillFile, Snapshot
from skill_atlas.readers import FallbackReader


class Primary:
    def resolve(self, repository):
        return Snapshot(repository, "a" * 40, "b" * 40)

    def skill_files(self, snapshot):
        yield SkillFile("api/SKILL.md", "c" * 40)

    def read_file(self, snapshot, file):
        return b"api"


class Fallback:
    def __init__(self):
        self.snapshots = []

    def skill_files(self, snapshot):
        self.snapshots.append(snapshot)
        return [SkillFile("git/SKILL.md", "d" * 40)]

    def read_file(self, snapshot, file):
        return b"git"


def test_small_repository_never_uses_fallback(repository):
    fallback = Fallback()
    reader = FallbackReader(Primary(), fallback)
    snapshot = reader.resolve(repository)
    files = list(reader.skill_files(snapshot))
    assert reader.read_file(snapshot, files[0]) == b"api"
    assert not fallback.snapshots


def test_truncation_discards_partial_results_and_preserves_snapshot(repository):
    class Truncated(Primary):
        def skill_files(self, snapshot):
            yield from super().skill_files(snapshot)
            raise IncompleteListingError("truncated")

    fallback = Fallback()
    reader = FallbackReader(Truncated(), fallback)
    snapshot = reader.resolve(repository)
    files = list(reader.skill_files(snapshot))
    assert [file.path for file in files] == ["git/SKILL.md"]
    assert reader.read_file(snapshot, files[0]) == b"git"
    assert fallback.snapshots == [snapshot]


def test_access_failures_do_not_trigger_fallback(repository):
    class Denied(Primary):
        def skill_files(self, snapshot):
            raise RepositoryError("access denied")

    fallback = Fallback()
    reader = FallbackReader(Denied(), fallback)
    with pytest.raises(RepositoryError, match="access denied"):
        reader.skill_files(reader.resolve(repository))
    assert not fallback.snapshots
