from dataclasses import replace
from types import SimpleNamespace

import pytest

from skill_atlas.application.grouping import SkillGroups, fingerprint, validate_groups
from skill_atlas.errors import GroupingError
from skill_atlas.grouping import GroupingCatalog, Perspective, SkillIdentity
from skill_atlas.models import Repository


def test_complete_overlapping_groups_preserve_exact_identities(scan_result):
    skills = (
        *scan_result.skills,
        replace(scan_result.skills[0], repository=Repository("other", "repo")),
    )
    groups = validate_groups(
        {
            "groups": [
                {"title": "Review code", "skill_ids": ["s1", "s3"]},
                {"title": "Prepare releases", "skill_ids": ["s1", "s2"]},
            ]
        },
        skills,
    )
    assert groups[0].members == (SkillIdentity.of(skills[0]), SkillIdentity.of(skills[2]))
    assert groups[1].members == (SkillIdentity.of(skills[0]), SkillIdentity.of(skills[1]))


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"groups": []},
        {"groups": "bad"},
        {"groups": [], "extra": True},
        {"groups": [None]},
        {"groups": [{"title": "Code"}]},
        {"groups": [{"title": "", "skill_ids": ["s1", "s2"]}]},
        {"groups": [{"title": 42, "skill_ids": ["s1", "s2"]}]},
        {"groups": [{"title": "x" * 161, "skill_ids": ["s1", "s2"]}]},
        {"groups": [{"title": "Other", "skill_ids": ["s1", "s2"]}]},
        {"groups": [{"title": "Code", "skill_ids": []}]},
        {"groups": [{"title": "Code", "skill_ids": "s1"}]},
        {"groups": [{"title": "Code", "skill_ids": ["s1"]}]},
        {"groups": [{"title": "Code", "skill_ids": ["s1", "s2", "s3"]}]},
        {"groups": [{"title": "Code", "skill_ids": ["s1", "s2", "s1"]}]},
        {"groups": [{"title": "Code", "skill_ids": ["s1", {}]}]},
        {
            "groups": [
                {"title": "Code", "skill_ids": ["s1"]},
                {"title": " code ", "skill_ids": ["s2"]},
            ]
        },
    ],
)
def test_invalid_or_incomplete_response_rejected(payload, scan_result):
    with pytest.raises(GroupingError, match="incomplete or invalid"):
        validate_groups(payload, scan_result.skills)


def test_metadata_fingerprint_ignores_order_and_commit_only_changes(scan_result):
    skills = scan_result.skills
    assert fingerprint(skills) == fingerprint(
        tuple(replace(s, commit_sha="b" * 40) for s in reversed(skills))
    )
    for field in ("name", "description", "path"):
        assert fingerprint(skills) != fingerprint(
            (replace(skills[0], **{field: "changed"}), skills[1])
        )
    assert fingerprint(skills) != fingerprint(skills[:1])


def test_empty_catalog_never_calls_provider_or_save():
    store = SimpleNamespace(read=lambda _: GroupingCatalog((), None))
    with pytest.raises(GroupingError, match="No saved skills"):
        SkillGroups(store).generate(Perspective.TOPICS, SimpleNamespace())
