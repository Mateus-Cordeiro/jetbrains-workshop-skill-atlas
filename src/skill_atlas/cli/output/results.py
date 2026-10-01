"""Adapt completed application results to a shared terminal presentation."""

from dataclasses import dataclass

from skill_atlas.application.catalog import FilteredSkills
from skill_atlas.application.similarity import SimilarityResult
from skill_atlas.cli.output.text import location_text, summary
from skill_atlas.models import ScanResult, Skill

STAR = "★"


def starred_name(skill: Skill) -> str:
    return f"{skill.name} {STAR}" if skill.starred else skill.name


@dataclass(frozen=True)
class SkillEntry:
    locations: tuple[Skill, ...]
    score: int | None = None

    @property
    def skill(self) -> Skill:
        return self.locations[0]

    def heading(self, index: int) -> str:
        score = f" · {self.score}%" if self.score is not None else ""
        return f"{index}. {starred_name(self.skill)}{score}"

    def location(self, skill: Skill) -> str:
        """Grouped locations are separate identities, so each shows its own star."""
        starred = len(self.locations) > 1 and skill.starred
        return location_text(skill) + (f" {STAR}" if starred else "")


@dataclass(frozen=True)
class ResultsView:
    title: str
    entries: tuple[SkillEntry, ...]
    empty_message: str
    source: Skill | None = None
    guidance: str = ""


def scan_view(result: ScanResult) -> ResultsView:
    return ResultsView(
        summary(result),
        tuple(SkillEntry((skill,)) for skill in result.skills),
        "No skills found in the repository",
    )


def filter_view(result: FilteredSkills) -> ResultsView:
    count = len(result.matches)
    starred = "starred " if result.starred else ""
    return ResultsView(
        f"{count} matching {starred}{'skill' if count == 1 else 'skills'}",
        tuple(SkillEntry((skill,)) for skill in result.matches),
        f"No {starred or 'saved '}skills in the selected scope"
        if not result.total_count
        else "No skills match the query",
    )


def similarity_view(result: SimilarityResult) -> ResultsView:
    count = len(result.matches)
    groups = "group" if count == 1 else "groups"
    return ResultsView(
        f"Similar to {starred_name(result.source)} — {count} result {groups}",
        tuple(SkillEntry(match.locations, match.display_score) for match in result.matches),
        "No similar skills found.",
        source=result.source,
        guidance=(
            "Scores compare names and descriptions, not document bodies or quality. "
            "Even 100% does not prove identical instructions. "
            "Scores can change as the catalog grows."
        ),
    )
