from dataclasses import replace

import pytest

from skill_atlas.application.catalog import BrowseCatalog, filter_skills
from skill_atlas.models import RepositorySummary


@pytest.mark.parametrize(
    ("query", "indices"),
    [
        ("", [0, 1]),
        (" \t\n ", [0, 1]),
        ("REVIEW", [0]),
        ("code maintain", [0]),
        ("  NOTES\nDraft ", [1]),
        ("review notes", []),
        ("SKILL.md", []),
        ("Acme", []),
        ("%", []),
        ("_", []),
        (".*", []),
    ],
)
def test_matching_uses_all_literal_terms_in_names_or_descriptions(scan_result, query, indices):
    assert filter_skills(scan_result.skills, query) == tuple(
        scan_result.skills[index] for index in indices
    )


def test_matching_unicode_and_duplicate_names_preserves_order(scan_result):
    first = replace(scan_result.skills[0], name="Straße", description="100% café_name")
    second = replace(first, path="other/SKILL.md")
    skills = (first, second)
    assert filter_skills(skills, "STRASSE CAFÉ") == skills
    assert filter_skills(skills, "100% _name") == skills
    assert filter_skills(skills, "1000 caféXname") == ()


def test_unfiltered_home_only_reads_summaries(scan_result):
    summary = RepositorySummary(scan_result.repository, 2, scan_result.commit_sha)

    class Catalog:
        def repositories(self):
            return (summary,)

        def skills(self, repository=None):
            pytest.fail("Collapsed browsing must not load all skill metadata")

    view = BrowseCatalog(Catalog()).home("  ")
    assert view.repositories[0].summary == summary
    assert view.repositories[0].skills == ()


@pytest.mark.parametrize("query, count", [("", 2), (" \t ", 2), ("CODE maintain", 1), ("none", 0)])
def test_filter_returns_matches_and_scope_count(scan_result, query, count):
    class Catalog:
        def skills(self, repository=None):
            return scan_result.skills if repository == scan_result.repository else ()

    browser = BrowseCatalog(Catalog())
    result = browser.filter(query, scan_result.repository)
    assert result.total_count == 2
    assert result.matches == scan_result.skills[:count]
    assert browser.filter(query).total_count == 0
    assert browser.filter(query).matches == ()


class StarredCatalog:
    """Catalog reads with one starred copy among same-name skills in two repositories."""

    def __init__(self, scan_result):
        from skill_atlas.models import Repository

        review, notes = scan_result.skills
        other = Repository("other", "repo")
        self.rows = (
            replace(review, path="copy/SKILL.md"),
            replace(review, starred=True),
            notes,
            replace(review, repository=other, starred=True),
        )
        self.reads = 0

    def skills(self, repository=None):
        self.reads += 1
        return tuple(
            skill for skill in self.rows if repository is None or skill.repository == repository
        )

    def repositories(self):
        pytest.fail("A starred-only homepage groups one skill snapshot instead of summaries")


@pytest.mark.parametrize(
    ("query", "starred", "paths", "total"),
    [
        ("", False, ["copy/SKILL.md", "review/SKILL.md", "release notes/SKILL.md"], 3),
        ("", True, ["review/SKILL.md"], 1),
        (" \t ", True, ["review/SKILL.md"], 1),
        ("CODE maintain", True, ["review/SKILL.md"], 1),
        ("notes", True, [], 1),
    ],
)
def test_starred_scope_restricts_matches_without_changing_matching(
    scan_result, query, starred, paths, total
):
    catalog = StarredCatalog(scan_result)
    result = BrowseCatalog(catalog).filter(query, scan_result.repository, starred)
    assert [skill.path for skill in result.matches] == paths
    assert (result.total_count, result.starred) == (total, starred)
    assert catalog.reads == 1
    view = BrowseCatalog(catalog).repository(
        scan_result.repository, query, "copy/SKILL.md", starred
    )
    assert [skill.path for skill in view.matches] == paths
    assert len(view.skills) == 3 and view.selected.path == "copy/SKILL.md"


def test_starred_homepage_groups_starred_matches_with_repository_totals(scan_result):
    catalog = StarredCatalog(scan_result)
    view = BrowseCatalog(catalog).home("", starred=True)
    assert [
        (group.summary.repository.full_name, group.summary.skill_count, len(group.skills))
        for group in view.repositories
    ] == [("Acme/skills", 3, 1), ("other/repo", 1, 1)]
    assert view.matching_count == 2 and catalog.reads == 1
    assert BrowseCatalog(catalog).home("notes", starred=True).repositories == ()


@pytest.mark.parametrize(
    "sort, expected",
    [("none", ["a", "b", "c"]), ("asc", ["b", "c", "a"]), ("desc", ["a", "b", "c"])],
)
@pytest.mark.parametrize("filtered", [False, True])
def test_home_sort_uses_total_counts_and_url_ties(scan_result, sort, expected, filtered):
    from skill_atlas.models import Repository

    repositories = [Repository("acme", name) for name in ("a", "b", "c")]
    summaries = tuple(
        RepositorySummary(repository, count, scan_result.commit_sha)
        for repository, count in zip(repositories, (3, 1, 1), strict=True)
    )

    class Catalog:
        def repositories(self):
            assert not filtered
            return summaries

        def skills(self):
            assert filtered
            return tuple(
                replace(
                    scan_result.skills[0],
                    repository=summary.repository,
                    path=f"{i}/SKILL.md",
                    starred=i == 0,
                )
                for summary in summaries
                for i in range(summary.skill_count)
            )

    view = BrowseCatalog(Catalog()).home("review" if filtered else "", filtered, sort)
    assert [group.summary.repository.name for group in view.repositories] == expected
    assert view.matching_count == (3 if filtered else 0)
    assert [len(group.skills) for group in view.repositories] == ([1] * 3 if filtered else [0] * 3)
