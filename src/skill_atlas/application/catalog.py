"""Read-only catalog browsing and shared name/description matching rules."""

from dataclasses import dataclass
from itertools import groupby

from skill_atlas.models import Repository, RepositorySummary, Skill
from skill_atlas.ports import CatalogReader


def filter_skills(skills: tuple[Skill, ...], query: str) -> tuple[Skill, ...]:
    terms = query.casefold().split()
    return tuple(
        skill
        for skill in skills
        if all(
            term in skill.name.casefold() or term in skill.description.casefold() for term in terms
        )
    )


@dataclass(frozen=True)
class FilteredSkills:
    total_count: int
    matches: tuple[Skill, ...]


@dataclass(frozen=True)
class RepositoryMatches:
    summary: RepositorySummary
    skills: tuple[Skill, ...]


@dataclass(frozen=True)
class CatalogView:
    repositories: tuple[RepositoryMatches, ...]
    matching_count: int


@dataclass(frozen=True)
class RepositoryView:
    repository: Repository
    skills: tuple[Skill, ...]
    matches: tuple[Skill, ...]
    selected: Skill | None


class BrowseCatalog:
    def __init__(self, catalog: CatalogReader) -> None:
        self.catalog = catalog

    def filter(self, query: str = "", repository: Repository | None = None) -> FilteredSkills:
        skills = self.catalog.skills(repository)
        return FilteredSkills(len(skills), filter_skills(skills, query))

    def home(self, query: str = "") -> CatalogView:
        if not query.strip():
            return CatalogView(
                tuple(RepositoryMatches(summary, ()) for summary in self.catalog.repositories()),
                0,
            )
        # Counts and matches come from one read snapshot, including during a rescan.
        groups = []
        for _, rows in groupby(self.catalog.skills(), key=lambda skill: skill.repository.url):
            skills = tuple(rows)
            matches = filter_skills(skills, query)
            if matches:
                first = skills[0]
                summary = RepositorySummary(first.repository, len(skills), first.commit_sha)
                groups.append(RepositoryMatches(summary, matches))
        return CatalogView(tuple(groups), sum(len(group.skills) for group in groups))

    def repository(
        self, repository: Repository, query: str = "", selected_path: str = ""
    ) -> RepositoryView:
        skills = self.catalog.skills(repository)
        return RepositoryView(
            repository,
            skills,
            filter_skills(skills, query),
            next((skill for skill in skills if skill.path == selected_path), None),
        )
