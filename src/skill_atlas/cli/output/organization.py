"""Printed summary for organization scans; results are browsed with filter or serve."""

from rich.console import Console
from rich.text import Text

from skill_atlas.application.organization_scan import OrganizationScanResult, RepositoryOutcome
from skill_atlas.cli.output.text import display_text


def _count(count: int, noun: str, plural: str) -> str:
    return f"{count} {noun if count == 1 else plural}"


def _status(outcome: RepositoryOutcome) -> str:
    if outcome.state == "succeeded":
        return (
            _count(outcome.skill_count, "skill", "skills") if outcome.skill_count else "no skills"
        )
    if outcome.state == "failed":
        return f"failed: {outcome.error}"
    return "empty" if outcome.state == "empty" else "not scanned"


def organization_summary(result: OrganizationScanResult) -> tuple[str, ...]:
    repositories = _count(len(result.repositories), "repository", "repositories")
    skills = _count(result.skill_count, "skill", "skills")
    lines = [f"{result.organization.full_name} — {repositories}, {skills}"]
    lines.extend(
        f"{outcome.repository.full_name} — {_status(outcome)}" for outcome in result.repositories
    )
    if not result.repositories:
        lines.append("No repositories to scan in the organization")
    return tuple(display_text(line, single_line=True) for line in lines)


def print_organization_summary(result: OrganizationScanResult, console: Console) -> None:
    for line in organization_summary(result):
        # One line per repository, even when stdout is redirected to a narrow default width.
        console.print(Text(line), soft_wrap=True)
