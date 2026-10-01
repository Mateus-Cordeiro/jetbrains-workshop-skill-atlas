"""Narrow structural interfaces consumed by application services."""

from collections.abc import Iterable
from typing import Protocol

from skill_atlas.grouping import Grouping, GroupingCatalog, GroupingSnapshot, Perspective
from skill_atlas.models import (
    Organization,
    OrganizationListing,
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


class OrganizationReader(Protocol):
    def list_repositories(self, organization: Organization) -> OrganizationListing: ...


class SkillParser(Protocol):
    def parse(self, content: bytes) -> SkillMetadata | None: ...


class Catalog(Protocol):
    def replace_repository(self, result: ScanResult) -> None: ...


class CatalogReader(Protocol):
    def repositories(self) -> tuple[RepositorySummary, ...]: ...

    def skills(self, repository: Repository | None = None) -> tuple[Skill, ...]: ...

    def skill(self, repository: Repository, path: str) -> Skill | None: ...


class DocumentReader(Protocol):
    def read_document(self, skill: Skill) -> bytes: ...


class GroupingProvider(Protocol):
    model: str

    def group(self, skills: tuple[Skill, ...], perspective: Perspective) -> object: ...


class GroupingStore(Protocol):
    def read(self, perspective: Perspective) -> GroupingCatalog: ...

    def read_all(self) -> GroupingSnapshot: ...

    def save(self, groupings: tuple[Grouping, ...]) -> None: ...
