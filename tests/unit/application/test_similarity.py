from dataclasses import replace
from types import SimpleNamespace

import pytest

from skill_atlas.application.similarity import MissingSimilaritySource, SimilarMatch, SimilarSkills
from skill_atlas.models import Repository, Skill

REPO = Repository("acme", "skills")


def skill(name, description, path="SKILL.md", repository=REPO):
    return Skill(repository, path, name, description, "a" * 40)


def search(source, *candidates):
    catalog = SimpleNamespace(all_skills=lambda: (source, *candidates))
    return SimilarSkills(catalog).search(source.repository, source.path).matches


def test_relevance_prefers_purpose_to_name_and_omits_unrelated():
    source = skill("code-review", "Review code changes for correctness and maintainability.")
    purpose = skill("patch-audit", source.description, "purpose/SKILL.md")
    misleading_name = skill(source.name, "Bake sourdough bread.", "wrong/SKILL.md")
    unrelated = skill("weather", "Predict rainfall.", "weather/SKILL.md")
    matches = search(source, unrelated, misleading_name, purpose)
    assert [match.skill for match in matches] == [purpose, misleading_name]
    assert matches[0].score == pytest.approx(80)
    assert matches[1].score == pytest.approx(20)
    assert [match.display_score for match in matches] == [80, 20]
    # The best result remains 80, even when it is the only candidate.
    assert search(source, purpose)[0].display_score == 80


def test_identity_copies_groups_and_all_repositories_do_not_change_scores():
    source = skill("review", "Check patches carefully.")
    local = replace(source, path=".agents/SKILL.md")
    remote = replace(source, repository=Repository("other", "repo"))
    same_name = replace(remote, path="different/SKILL.md", description="Bake bread.")
    baseline = search(source, remote, same_name)
    duplicates = search(source, local, remote, same_name, replace(remote, path="copy/SKILL.md"))
    assert len(duplicates) == 2
    assert duplicates[0].score == baseline[0].score
    assert duplicates[1].score == baseline[1].score
    assert source not in duplicates[0].locations
    assert len(duplicates[0].locations) == 3
    assert duplicates[0].display_score == 100
    assert local in duplicates[0].locations
    assert remote in duplicates[0].locations


def test_grouping_normalizes_unicode_case_and_whitespace_without_discarding_punctuation():
    source = skill("Résumé", "Review Ｃ++ code.")
    copy = replace(source, path="copy", name="RÉSUMÉ", description="  review C++  code. ")
    different = replace(copy, path="different", description="Review C++ code!")
    matches = search(source, copy, different)
    assert len(matches) == 2  # Token equality is not metadata equality.
    assert all(match.display_score == 100 for match in matches)
    extra_copy = replace(copy, path="another", name="résumé")
    expanded = search(source, copy, different, extra_copy)
    assert len(expanded) == 2
    assert expanded[0].score == matches[0].score


@pytest.mark.parametrize("name", ["code-review", "CODE_REVIEW", "Code review"])
def test_names_split_separators_and_preserve_technical_tokens(name):
    source = skill(name, "C++ C# Python")
    candidate = skill("code review", "C++ C# Python", "other")
    match = search(source, candidate)[0]
    assert match.display_score == 100
    c_only = skill("different", "C", "plain")
    assert search(source, c_only) == ()


def test_phrases_reward_adjacent_words():
    source = skill("source", "review code safely")
    adjacent = skill("candidate", "review code", "adjacent")
    reordered = skill("candidate", "code review", "reordered")
    matches = search(source, reordered, adjacent)
    assert [match.skill for match in matches] == [adjacent, reordered]
    assert matches[0].score > matches[1].score


def test_repetition_does_not_create_unbounded_scores():
    source = skill("source", "python review")
    candidate = skill("source", "python " * 100 + "review", "other")
    match = search(source, candidate)[0]
    assert 10 <= match.score < 100


@pytest.mark.parametrize("description", ["and the skills", "!!!", ""])
def test_empty_vocabularies_are_finite_and_do_not_manufacture_matches(description):
    source = skill("!!!", description)
    assert search(source, replace(source, path="copy")) == ()
    assert search(source) == ()


def test_ties_and_limit_are_deterministic():
    source = skill("review", "alpha beta gamma delta")
    candidates = [skill(f"candidate{i:02}", source.description, f"path{i:02}") for i in range(15)]
    matches = search(source, *reversed(candidates))
    assert len(matches) == 10
    assert [match.skill for match in matches] == candidates[:10]
    assert matches == search(source, *candidates)


def test_display_rounding_and_missing_source():
    candidate = skill("test", "description")
    assert SimilarMatch((candidate,), 82.5).display_score == 83
    with pytest.raises(MissingSimilaritySource, match="starting skill"):
        SimilarSkills(SimpleNamespace(all_skills=lambda: ())).search(REPO, "missing")


def test_lexical_limitations_remain_explicit():
    source = skill("outage", "Diagnose production outages")
    synonym = skill("incident", "Investigate service incidents", "synonym")
    assert search(source, synonym) == ()
    exclusion = skill("excluded", "Do not diagnose production outages", "excluded")
    # Lexical overlap cannot interpret negation; do not imply semantic understanding.
    assert search(source, exclusion)[0].score > 10


def test_relevance_set_ranks_task_alternatives_above_incidental_overlap():
    source = skill("code-review", "Review code changes for correctness and maintainability.")
    examples = [
        ("patch-review", "Review code patches for correctness, bugs, and maintainability."),
        (
            "pull-request-review",
            "Review code changes and identify correctness issues before merging pull requests.",
        ),
        ("code-review", "Draft release announcements for customers."),
        ("github-releases", "Publish release announcements to GitHub and notify customers."),
        ("python-format", "Format Python files and sort imports using Ruff."),
        ("incident-response", "Investigate failing services and restore production availability."),
        ("presentation", "Create slide decks and speaker notes for technical workshops."),
    ]
    candidates = [
        skill(name, description, str(i)) for i, (name, description) in enumerate(examples)
    ]
    matches = search(source, *candidates)
    assert [match.skill for match in matches] == candidates[:3]
    assert matches[0].score > matches[1].score > matches[2].score
