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
