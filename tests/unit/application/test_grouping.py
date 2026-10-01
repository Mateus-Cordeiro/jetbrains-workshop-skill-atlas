from dataclasses import replace
from types import SimpleNamespace

import pytest

from skill_atlas.application.grouping import SkillGroups, fingerprint, validate_groups
from skill_atlas.errors import GroupingError
from skill_atlas.grouping import GroupingSnapshot, Perspective, SkillIdentity
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


@pytest.mark.parametrize("count", [12, 13])
def test_group_limit_preserves_coverage_and_overlap_without_truncation(count, scan_result):
    payload = {
        "groups": [{"title": f"Capability {i}", "skill_ids": ["s1", "s2"]} for i in range(count)]
    }
    if count == 13:
        with pytest.raises(GroupingError, match="13 groups; the maximum is 12"):
            validate_groups(payload, scan_result.skills)
    else:
        groups = validate_groups(payload, scan_result.skills)
        assert len(groups) == 12
        assert all(len(group.members) == 2 for group in groups)


def test_missing_skill_error_reports_count_without_metadata(scan_result):
    with pytest.raises(GroupingError, match="Missing 1 of 2 skills"):
        validate_groups({"groups": [{"title": "Code", "skill_ids": ["s1"]}]}, scan_result.skills)


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
    store = SimpleNamespace(read_all=lambda: GroupingSnapshot((), ()))
    with pytest.raises(GroupingError, match="No saved skills"):
        SkillGroups(store).generate(SimpleNamespace())


def test_both_perspectives_share_one_snapshot_and_publish_together(scan_result):
    seen, saved = [], []
    store = SimpleNamespace(
        read_all=lambda: GroupingSnapshot(scan_result.skills, ()), save=saved.append
    )

    def group(skills, perspective):
        seen.append((skills, perspective))
        return {"groups": [{"title": perspective.value, "skill_ids": ["s1", "s2"]}]}

    result = SkillGroups(store).generate(SimpleNamespace(model="test", group=group))
    assert [p for _, p in seen] == list(Perspective)
    assert all(skills is scan_result.skills for skills, _ in seen)
    assert saved == [result] and len(result) == 2
    assert result[0].fingerprint == result[1].fingerprint


def test_invalid_second_perspective_does_not_publish_first(scan_result):
    saved = []

    def group(skills, perspective):
        return (
            {"groups": [{"title": "Code", "skill_ids": ["s1", "s2"]}]}
            if perspective == Perspective.TOPICS
            else {}
        )

    store = SimpleNamespace(
        read_all=lambda: GroupingSnapshot(scan_result.skills, ()), save=saved.append
    )
    with pytest.raises(GroupingError, match="Capabilities generation failed.*Expected only"):
        SkillGroups(store).generate(SimpleNamespace(model="test", group=group))
    assert saved == []
