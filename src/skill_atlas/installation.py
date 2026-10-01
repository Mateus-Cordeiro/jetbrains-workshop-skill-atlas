"""Installation identities, portable paths, and versioned ownership records."""

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Literal

from skill_atlas.errors import AtlasError
from skill_atlas.models import Repository

Agent = Literal["codex", "claude"]
AGENT_DIRECTORIES = {"codex": ".agents/skills", "claude": ".claude/skills"}


class InstallationError(AtlasError):
    """Installation cannot proceed without risking ownership or file contents."""


def relative_path(value: str) -> str:
    parts = value.split("/")
    if not value or any(
        part in {"", ".", ".."}
        or part.endswith((".", " "))
        or any(ord(c) < 32 or c in '\\:<>"|?*' for c in part)
        or part.casefold() == ".git"
        for part in parts
    ):
        raise InstallationError(f"Unsafe relative path: {value!r}")
    return value


def source_path(value: str) -> str:
    relative_path(value)
    if PurePosixPath(value).name != "SKILL.md":
        raise InstallationError("Select the exact repository-relative SKILL.md path.")
    return value


def target_directory(agent: str, name: str) -> str:
    if agent not in AGENT_DIRECTORIES:
        raise InstallationError("Choose an agent: codex or claude.")
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}", name):
        raise InstallationError(
            "Choose a folder name (--name in CLI) with 1–64 letters, digits, "
            "hyphens or underscores."
        )
    return f"{AGENT_DIRECTORIES[agent]}/{name}"


def checked_commit(value: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise InstallationError("An installation requires a full recorded commit SHA.")
    return value


@dataclass(frozen=True)
class BundleFile:
    path: str
    content: bytes
    executable: bool = False


@dataclass(frozen=True)
class FileHash:
    path: str
    sha256: str
    executable: bool


def hashes(bundle: tuple[BundleFile, ...]) -> tuple[FileHash, ...]:
    paths: set[str] = set()
    directories: set[str] = set()
    total = 0
    for file in bundle:
        relative_path(file.path)
        key = unicodedata.normalize("NFC", file.path).casefold()
        if key in paths or key in directories:
            raise InstallationError(f"Bundle path collision: {file.path}")
        paths.add(key)
        for parent in PurePosixPath(key).parents:
            if str(parent) != ".":
                if str(parent) in paths:
                    raise InstallationError(f"Bundle path collision: {file.path}")
                directories.add(str(parent))
        total += len(file.content)
    if "SKILL.md" not in {file.path for file in bundle}:
        raise InstallationError("The bundle does not contain a regular SKILL.md.")
    if len(bundle) > 10000 or total > 128 * 1024 * 1024:
        raise InstallationError("The bundle exceeds 10,000 files or 128 MiB.")
    return tuple(
        FileHash(f.path, hashlib.sha256(f.content).hexdigest(), f.executable)
        for f in sorted(bundle, key=lambda f: f.path)
    )


@dataclass(frozen=True)
class Installation:
    repository_url: str
    skill_path: str
    commit_sha: str
    agent: str
    destination: str
    files: tuple[FileHash, ...]

    @property
    def identity(self) -> tuple[str, str, str]:
        return self.repository_url, self.skill_path, self.agent

    def validate(self) -> None:
        if Repository.from_url(self.repository_url).url != self.repository_url:
            raise InstallationError("Noncanonical installation repository.")
        source_path(self.skill_path)
        checked_commit(self.commit_sha)
        if self.destination != target_directory(self.agent, self.destination.split("/")[-1]):
            raise InstallationError("Invalid installation destination.")
        seen: set[str] = set()
        for file in self.files:
            relative_path(file.path)
            if file.path in seen or not re.fullmatch(r"[0-9a-f]{64}", file.sha256):
                raise InstallationError("Invalid installation file hashes.")
            seen.add(file.path)
        if "SKILL.md" not in seen:
            raise InstallationError("Installation record is missing SKILL.md.")


@dataclass(frozen=True)
class InstallationStatus:
    installation: Installation
    conflicts: tuple[str, ...]
    catalog_commit: str | None

    @property
    def state(self) -> str:
        if self.conflicts:
            return "modified"
        if self.catalog_commit is None:
            return "source unavailable"
        if self.catalog_commit != self.installation.commit_sha:
            return "update available"
        return "current"
