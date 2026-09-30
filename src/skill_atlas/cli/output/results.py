"""Adapt completed application results to a shared terminal presentation."""

from dataclasses import dataclass

from skill_atlas.application.catalog import FilteredSkills
from skill_atlas.application.similarity import SimilarityResult
from skill_atlas.cli.output.text import summary
from skill_atlas.models import ScanResult, Skill


@dataclass(frozen=True)
class SkillEntry:
    locations: tuple[Skill, ...]
    score: int | None = None

    @property
    def skill(self) -> Skill:
        return self.locations[0]

    def heading(self, index: int) -> str:
        score = f" · {self.score}%" if self.score is not None else ""
        return f"{index}. {self.skill.name}{score}"


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
    return ResultsView(
        f"{count} matching {'skill' if count == 1 else 'skills'}",
        tuple(SkillEntry((skill,)) for skill in result.matches),
        "No saved skills in the selected scope"
        if not result.total_count
        else "No skills match the query",
    )


def similarity_view(result: SimilarityResult) -> ResultsView:
    count = len(result.matches)
    return ResultsView(
        f"Similar to {result.source.name} — {count} result {'group' if count == 1 else 'groups'}",
        tuple(SkillEntry(match.locations, match.display_score) for match in result.matches),
        "No similar skills found.",
        source=result.source,
        guidance=(
            "Scores compare names and descriptions, not document bodies or quality. "
            "Even 100% does not prove identical instructions. "
            "Scores can change as the catalog grows."
        ),
    )
