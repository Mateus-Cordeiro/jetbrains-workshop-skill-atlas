"""Generate and browse complete catalog groupings independently of the provider."""

import hashlib
import json
from dataclasses import dataclass

from skill_atlas.errors import GroupingError
from skill_atlas.grouping import Grouping, Perspective, SkillGroup, SkillIdentity
from skill_atlas.models import Skill
from skill_atlas.ports import GroupingProvider, GroupingStore


def fingerprint(skills: tuple[Skill, ...]) -> str:
    # Commits can move without changing classification input. Identities cannot.
    data = sorted((s.repository.url, s.path, s.name, s.description) for s in skills)
    return hashlib.sha256(json.dumps(data, ensure_ascii=False).encode()).hexdigest()


def validate_groups(payload: object, skills: tuple[Skill, ...]) -> tuple[SkillGroup, ...]:
    invalid = GroupingError(
        "The model returned incomplete or invalid groups. Previous groups are unchanged. "
        "Retry generation or choose another model."
    )
    if not isinstance(payload, dict) or set(payload) != {"groups"}:
        raise invalid
    groups = payload["groups"]
    if not isinstance(groups, list) or not groups:
        raise invalid
    identities = {f"s{i}": SkillIdentity.of(skill) for i, skill in enumerate(skills, 1)}
    seen: set[str] = set()
    titles: set[str] = set()
    result = []
    for group in groups:
        if not isinstance(group, dict) or set(group) != {"title", "skill_ids"}:
            raise invalid
        title, members = group["title"], group["skill_ids"]
        if not isinstance(title, str) or not title.strip() or len(title) > 160:
            raise invalid
        title = " ".join(title.split())
        key = title.casefold()
        if key in titles or key in {"other", "miscellaneous", "uncertain", "uncategorized"}:
            raise invalid
        if not isinstance(members, list) or not members:
            raise invalid
        if any(not isinstance(member, str) or member not in identities for member in members):
            raise invalid
        if len(set(members)) != len(members):
            raise invalid
        titles.add(key)
        seen.update(members)
        result.append(SkillGroup(title, tuple(identities[member] for member in members)))
    if seen != set(identities):
        raise invalid
    return tuple(result)


@dataclass(frozen=True)
class VisibleGroup:
    title: str
    skills: tuple[Skill, ...]


@dataclass(frozen=True)
class GroupingView:
    grouping: Grouping | None
    groups: tuple[VisibleGroup, ...]
    stale: bool
    skill_count: int
    selected: Skill | None


class SkillGroups:
    def __init__(self, store: GroupingStore) -> None:
        self.store = store

    def generate(self, perspective: Perspective, provider: GroupingProvider) -> Grouping:
        skills = self.store.read(perspective).skills
        if not skills:
            raise GroupingError("No saved skills to group. Scan a repository first.")
        groups = validate_groups(provider.group(skills, perspective), skills)
        grouping = Grouping(perspective, fingerprint(skills), provider.model, groups)
        self.store.save(grouping)
        return grouping

    def browse(
        self, perspective: Perspective, selected_identity: SkillIdentity | None = None
    ) -> GroupingView:
        data = self.store.read(perspective)
        skills = {SkillIdentity.of(skill): skill for skill in data.skills}
        groups = (
            tuple(
                VisibleGroup(group.title, tuple(skills[m] for m in group.members if m in skills))
                for group in data.grouping.groups
            )
            if data.grouping
            else ()
        )
        visible = tuple(group for group in groups if group.skills)
        selected = next(
            (s for g in visible for s in g.skills if SkillIdentity.of(s) == selected_identity), None
        )
        return GroupingView(
            data.grouping,
            visible,
            data.grouping is not None and data.grouping.fingerprint != fingerprint(data.skills),
            len(data.skills),
            selected,
        )
