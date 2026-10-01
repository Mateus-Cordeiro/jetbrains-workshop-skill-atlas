"""Narrow I/O contracts for project installation, independent of interfaces."""

from contextlib import AbstractContextManager
from pathlib import Path
from typing import Protocol

from skill_atlas.installation import BundleFile, FileHash, Installation
from skill_atlas.models import Skill


class BundleReader(Protocol):
    def read_bundle(self, skill: Skill) -> tuple[BundleFile, ...]: ...


class InstallationRecords(Protocol):
    def read(self) -> tuple[Installation, ...]: ...


class InstallationFiles(Protocol):
    def exists(self, path: str) -> bool: ...

    def conflicts(self, path: str, files: tuple[FileHash, ...]) -> tuple[str, ...]: ...


class InstallationTransaction(Protocol):
    @property
    def records(self) -> InstallationRecords: ...

    @property
    def files(self) -> InstallationFiles: ...

    def commit(
        self,
        records: tuple[Installation, ...],
        old: Installation | None,
        new: Installation | None,
        bundle: tuple[BundleFile, ...],
    ) -> None: ...


class ProjectInstallations(Protocol):
    def open(self, project: Path) -> AbstractContextManager[InstallationTransaction]: ...


class ProjectRegistry(Protocol):
    def list(self) -> tuple[Path, ...]: ...

    def register(self, project: Path) -> None: ...
