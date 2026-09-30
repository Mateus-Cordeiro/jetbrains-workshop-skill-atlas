"""Narrow structural interfaces consumed by application services."""

from collections.abc import Iterable
from typing import Protocol

from skill_atlas.models import (
    Repository,
    RepositorySummary,
    ScanResult,
    Skill,
    SkillFile,
    SkillMetadata,
    Snapshot,
)


class SnapshotReader(Protocol):
    def skill_files(self, snapshot: Snapshot) -> Iterable[SkillFile]: ...

    def read_file(self, snapshot: Snapshot, file: SkillFile) -> bytes: ...


class RepositoryReader(SnapshotReader, Protocol):
    def resolve(self, repository: Repository) -> Snapshot: ...


class SkillParser(Protocol):
    def parse(self, content: bytes) -> SkillMetadata | None: ...


class Catalog(Protocol):
    def replace_repository(self, result: ScanResult) -> None: ...


class CatalogReader(Protocol):
    def all_skills(self) -> tuple[Skill, ...]: ...

    def repositories(self) -> tuple[RepositorySummary, ...]: ...

    def skills(self, repository: Repository) -> tuple[Skill, ...]: ...

    def skill(self, repository: Repository, path: str) -> Skill | None: ...


class DocumentReader(Protocol):
    def read_document(self, skill: Skill) -> bytes: ...
