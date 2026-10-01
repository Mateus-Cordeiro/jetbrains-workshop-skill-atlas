"""Immutable values for saved, overlapping catalog groups."""

from dataclasses import dataclass
from enum import StrEnum

from skill_atlas.models import Skill


class Perspective(StrEnum):
    TOPICS = "topics"
    CAPABILITIES = "capabilities"


@dataclass(frozen=True)
class SkillIdentity:
    repository_url: str
    path: str

    @classmethod
    def of(cls, skill: Skill) -> "SkillIdentity":
        return cls(skill.repository.url, skill.path)


@dataclass(frozen=True)
class SkillGroup:
    title: str
    members: tuple[SkillIdentity, ...]


@dataclass(frozen=True)
class Grouping:
    perspective: Perspective
    fingerprint: str
    model: str
    groups: tuple[SkillGroup, ...]


@dataclass(frozen=True)
class GroupingCatalog:
    skills: tuple[Skill, ...]
    grouping: Grouping | None


@dataclass(frozen=True)
class GroupingSnapshot:
    skills: tuple[Skill, ...]
    groupings: tuple[Grouping, ...]
