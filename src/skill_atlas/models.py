"""Immutable values shared across component boundaries; no I/O dependencies."""

import re
from dataclasses import dataclass
from urllib.parse import quote, urlsplit


@dataclass(frozen=True)
class Repository:
    owner: str
    name: str

    @classmethod
    def from_url(cls, value: str) -> "Repository":
        try:
            parsed = urlsplit(value.strip())
            valid_origin = (
                parsed.scheme == "https"
                and parsed.hostname == "github.com"
                and parsed.port in (None, 443)
                and parsed.username is None
                and parsed.password is None
            )
        except ValueError:
            valid_origin = False
        if not valid_origin:
            raise ValueError(
                "Use a repository URL in the form https://github.com/owner/repository."
            )
        path = parsed.path.rstrip("/")
        if path.endswith(".git"):
            path = path[:-4]
        match = re.fullmatch(r"/([A-Za-z0-9-]+)/([A-Za-z0-9_.-]+)", path)
        if not match or parsed.query or parsed.fragment or match[2] in (".", ".."):
            raise ValueError(
                "Use a repository URL in the form https://github.com/owner/repository."
            )
        return cls(match[1], match[2])

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"

    @property
    def url(self) -> str:
        # GitHub repository names are case-insensitive; catalog identity is stable.
        return f"https://github.com/{self.full_name.lower()}"


@dataclass(frozen=True)
class Snapshot:
    repository: Repository
    commit_sha: str
    tree_sha: str


@dataclass(frozen=True)
class SkillFile:
    path: str
    blob_sha: str


@dataclass(frozen=True)
class SkillMetadata:
    name: str
    description: str


@dataclass(frozen=True)
class Skill:
    repository: Repository
    path: str
    name: str
    description: str
    commit_sha: str

    @property
    def url(self) -> str:
        return f"{self.repository.url}/blob/{self.commit_sha}/{quote(self.path, safe='/')}"


@dataclass(frozen=True)
class ScanResult:
    repository: Repository
    commit_sha: str
    skills: tuple[Skill, ...]
