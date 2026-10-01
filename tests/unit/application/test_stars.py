from dataclasses import replace

import pytest

from skill_atlas.application.stars import MissingStarredSkill, Stars


class MemoryStars:
    def __init__(self, skills):
        self.skills = {(skill.repository.url, skill.path): skill for skill in skills}
        self.starred = set()

    def set_starred(self, repository, path, starred):
        skill = self.skills.get((repository.url, path))
        if skill is None:
            return None
        (self.starred.add if starred else self.starred.discard)((repository.url, path))
        return replace(skill, starred=starred)


def test_star_and_unstar_are_idempotent_for_one_identity(scan_result):
    catalog = MemoryStars(scan_result.skills)
    stars = Stars(catalog)
    skill = scan_result.skills[0]
    for _ in range(2):
        assert stars.set(skill.repository, skill.path, True) == replace(skill, starred=True)
    assert catalog.starred == {(skill.repository.url, skill.path)}
    for _ in range(2):
        assert stars.set(skill.repository, skill.path, False) == skill
    assert catalog.starred == set()


def test_unknown_identity_is_reported_without_changing_stars(scan_result):
    catalog = MemoryStars(scan_result.skills)
    skill = scan_result.skills[0]
    for path in ("missing/SKILL.md", skill.path.upper()):
        with pytest.raises(MissingStarredSkill, match="Skill not found in the catalog"):
            Stars(catalog).set(skill.repository, path, True)
    assert catalog.starred == set()
