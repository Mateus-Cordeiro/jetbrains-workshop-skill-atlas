"""Read-only catalog browsing, shared name/description matching, and the starred scope."""

from dataclasses import dataclass
from itertools import groupby
from typing import Literal

from skill_atlas.models import Repository, RepositorySummary, Skill
from skill_atlas.ports import CatalogReader

RepositorySort = Literal["none", "asc", "desc"]


def filter_skills(skills: tuple[Skill, ...], query: str) -> tuple[Skill, ...]:
    terms = query.casefold().split()
    return tuple(
        skill
        for skill in skills
        if all(
            term in skill.name.casefold() or term in skill.description.casefold() for term in terms
        )
    )


def starred_scope(skills: tuple[Skill, ...], starred: bool) -> tuple[Skill, ...]:
    """Restrict the scope before matching; stars never change the matching rules."""
    return tuple(skill for skill in skills if skill.starred) if starred else skills


@dataclass(frozen=True)
class FilteredSkills:
    total_count: int
    matches: tuple[Skill, ...]
    starred: bool = False


@dataclass(frozen=True)
class RepositoryMatches:
    summary: RepositorySummary
    skills: tuple[Skill, ...]


def sort_repositories(
    groups: tuple[RepositoryMatches, ...], sort: RepositorySort
) -> tuple[RepositoryMatches, ...]:
    """Sort total stored counts; canonical URLs break ties in either direction."""
    direction = {"none": 0, "asc": 1, "desc": -1}[sort]
    return tuple(
        sorted(
            groups,
            key=lambda group: (
                direction * group.summary.skill_count,
                group.summary.repository.url,
            ),
        )
    )


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

    def filter(
        self, query: str = "", repository: Repository | None = None, starred: bool = False
    ) -> FilteredSkills:
        scope = starred_scope(self.catalog.skills(repository), starred)
        return FilteredSkills(len(scope), filter_skills(scope, query), starred)

    def home(
        self, query: str = "", starred: bool = False, sort: RepositorySort = "none"
    ) -> CatalogView:
        if not query.strip() and not starred:
            return CatalogView(
                sort_repositories(
                    tuple(
                        RepositoryMatches(summary, ()) for summary in self.catalog.repositories()
                    ),
                    sort,
                ),
                0,
            )
        # Counts and matches come from one read snapshot, including during a rescan.
        groups = []
        for _, rows in groupby(self.catalog.skills(), key=lambda skill: skill.repository.url):
            skills = tuple(rows)
            matches = filter_skills(starred_scope(skills, starred), query)
            if matches:
                first = skills[0]
                summary = RepositorySummary(first.repository, len(skills), first.commit_sha)
                groups.append(RepositoryMatches(summary, matches))
        return CatalogView(
            sort_repositories(tuple(groups), sort), sum(len(group.skills) for group in groups)
        )

    def repository(
        self,
        repository: Repository,
        query: str = "",
        selected_path: str = "",
        starred: bool = False,
    ) -> RepositoryView:
        skills = self.catalog.skills(repository)
        return RepositoryView(
            repository,
            skills,
            filter_skills(starred_scope(skills, starred), query),
            next((skill for skill in skills if skill.path == selected_path), None),
        )
