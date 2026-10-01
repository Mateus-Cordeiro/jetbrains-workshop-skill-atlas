"""Immutable values shared across component boundaries; no I/O dependencies."""

import re
from dataclasses import dataclass
from urllib.parse import SplitResult, quote, urlsplit

_OWNER = "[A-Za-z0-9-]+"
_SCAN_TARGET_ERROR = (
    "Use a repository URL in the form https://github.com/owner/repository, "
    "or an organization URL in the form https://github.com/organization."
)


def _github_url(value: str, message: str) -> SplitResult:
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
    if not valid_origin or parsed.query or parsed.fragment:
        raise ValueError(message)
    return parsed


@dataclass(frozen=True)
class Repository:
    owner: str
    name: str

    @classmethod
    def from_url(cls, value: str) -> "Repository":
        parsed = _github_url(
            value, "Use a repository URL in the form https://github.com/owner/repository."
        )
        path = parsed.path.rstrip("/")
        if path.endswith(".git"):
            path = path[:-4]
        match = re.fullmatch(rf"/({_OWNER})/([A-Za-z0-9_.-]+)", path)
        if not match or match[2] in (".", ".."):
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
class Organization:
    login: str

    @classmethod
    def from_url(cls, value: str) -> "Organization":
        parsed = _github_url(
            value, "Use an organization URL in the form https://github.com/organization."
        )
        match = re.fullmatch(rf"/({_OWNER})/?", parsed.path)
        if not match:
            raise ValueError("Use an organization URL in the form https://github.com/organization.")
        return cls(match[1])

    @property
    def full_name(self) -> str:
        """Display name, matching the role of ``Repository.full_name``."""
        return self.login

    @property
    def url(self) -> str:
        return f"https://github.com/{self.login.lower()}"


def scan_target(value: str) -> Repository | Organization:
    """Parse a scan URL; an owner without a repository names an organization."""
    for parse in (Repository.from_url, Organization.from_url):
        try:
            return parse(value)
        except ValueError:
            continue
    raise ValueError(_SCAN_TARGET_ERROR)


@dataclass(frozen=True)
class Snapshot:
    repository: Repository
    commit_sha: str
    tree_sha: str


@dataclass(frozen=True)
class OrganizationRepository:
    """A listed organization repository; ``snapshot`` is None for an empty repository."""

    repository: Repository
    fork: bool
    archived: bool
    snapshot: Snapshot | None


@dataclass(frozen=True)
class OrganizationListing:
    organization: Organization
    repositories: tuple[OrganizationRepository, ...]


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
    # Local catalog state for this identity, not scanned metadata or a GitHub star.
    starred: bool = False

    @property
    def url(self) -> str:
        return f"{self.repository.url}/blob/{self.commit_sha}/{quote(self.path, safe='/')}"


@dataclass(frozen=True)
class ScanResult:
    repository: Repository
    commit_sha: str
    skills: tuple[Skill, ...]


@dataclass(frozen=True)
class RepositorySummary:
    repository: Repository
    skill_count: int
    commit_sha: str


@dataclass(frozen=True)
class RepositoryFile:
    path: str
    blob_sha: str
    executable: bool
