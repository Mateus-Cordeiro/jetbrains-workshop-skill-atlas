from io import StringIO

from rich.console import Console

from skill_atlas.application.organization_scan import OrganizationScanResult, RepositoryOutcome
from skill_atlas.cli.output.organization import organization_summary, print_organization_summary
from skill_atlas.models import Organization, Repository


def outcome(name, state, skills=0, error=None):
    return RepositoryOutcome(Repository("acme", name), state, skills, error)


def test_summary_lists_each_repository_outcome_after_the_totals():
    result = OrganizationScanResult(
        Organization("acme"),
        (
            outcome("alpha", "succeeded", 1),
            outcome("beta", "succeeded", 3),
            outcome("docs", "succeeded"),
            outcome("empty", "empty"),
            outcome("broken", "failed", error="GitHub denied access.\x1b[31m"),
            outcome("later", "not_scanned"),
        ),
    )
    assert organization_summary(result) == (
        "acme — 6 repositories, 4 skills",
        "acme/alpha — 1 skill",
        "acme/beta — 3 skills",
        "acme/docs — no skills",
        "acme/empty — empty",
        "acme/broken — failed: GitHub denied access.",
        "acme/later — not scanned",
    )


def test_single_and_empty_organizations_use_singular_and_empty_wording():
    single = OrganizationScanResult(Organization("acme"), (outcome("only", "succeeded", 1),))
    assert organization_summary(single)[0] == "acme — 1 repository, 1 skill"
    empty = OrganizationScanResult(Organization("acme"), ())
    assert organization_summary(empty) == (
        "acme — 0 repositories, 0 skills",
        "No repositories to scan in the organization",
    )


def test_printed_summary_keeps_one_line_per_repository_on_narrow_output():
    reason = "A long failure reason that would otherwise wrap at a narrow width. " * 3
    result = OrganizationScanResult(
        Organization("acme"), (outcome("broken", "failed", error=reason.strip()),)
    )
    output = StringIO()
    print_organization_summary(result, Console(file=output, width=40, force_terminal=False))
    assert output.getvalue().splitlines() == list(organization_summary(result))
