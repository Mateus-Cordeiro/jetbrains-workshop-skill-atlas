"""Generate and browse complete catalog groupings independently of the provider."""

import hashlib
import json
from dataclasses import dataclass

from skill_atlas.errors import GroupingError
from skill_atlas.grouping import (
    MAX_GROUPS,
    Grouping,
    GroupingCatalog,
    Perspective,
    SkillGroup,
    SkillIdentity,
)
from skill_atlas.models import Skill
from skill_atlas.ports import GroupingProvider, GroupingStore


def fingerprint(skills: tuple[Skill, ...]) -> str:
    # Commits can move without changing classification input. Identities cannot.
    data = sorted((s.repository.url, s.path, s.name, s.description) for s in skills)
    return hashlib.sha256(json.dumps(data, ensure_ascii=False).encode()).hexdigest()


def validate_groups(payload: object, skills: tuple[Skill, ...]) -> tuple[SkillGroup, ...]:
    def invalid(reason: str) -> GroupingError:
        return GroupingError(
            f"The model returned incomplete or invalid groups: {reason} "
            "Retry generation or choose another model."
        )

    if not isinstance(payload, dict) or set(payload) != {"groups"}:
        raise invalid("Expected only a groups field.")
    groups = payload["groups"]
    if not isinstance(groups, list) or not groups:
        raise invalid("Expected a nonempty list of groups.")
    if len(groups) > MAX_GROUPS:
        raise invalid(f"Returned {len(groups)} groups; the maximum is {MAX_GROUPS}.")
    identities = {f"s{i}": SkillIdentity.of(skill) for i, skill in enumerate(skills, 1)}
    seen: set[str] = set()
    titles: set[str] = set()
    result = []
    for group in groups:
        if not isinstance(group, dict) or set(group) != {"title", "skill_ids"}:
            raise invalid("Each group must contain only a title and skill IDs.")
        title, members = group["title"], group["skill_ids"]
        if not isinstance(title, str) or not title.strip() or len(title) > 160:
            raise invalid("Titles must contain 1 to 160 characters.")
        title = " ".join(title.split())
        key = title.casefold()
        if key in titles:
            raise invalid("Group titles must be unique.")
        if key in {"other", "miscellaneous", "uncertain", "uncategorized"}:
            raise invalid("Generic catch-all group titles are not allowed.")
        if not isinstance(members, list) or not members:
            raise invalid("Every group must contain skills.")
        if any(not isinstance(member, str) or member not in identities for member in members):
            raise invalid("A group contains an unknown or invalid skill ID.")
        if len(set(members)) != len(members):
            raise invalid("A skill occurs more than once in the same group.")
        titles.add(key)
        seen.update(members)
        result.append(SkillGroup(title, tuple(identities[member] for member in members)))
    if seen != set(identities):
        raise invalid(f"Missing {len(set(identities) - seen)} of {len(identities)} skills.")
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

    def generate(self, provider: GroupingProvider) -> tuple[Grouping, ...]:
        # Both model calls share one catalog snapshot. Publish neither until both validate.
        skills = self.store.read_all().skills
        if not skills:
            raise GroupingError("No saved skills to group. Scan a repository first.")
        version = fingerprint(skills)
        results = []
        for perspective in Perspective:
            try:
                groups = validate_groups(provider.group(skills, perspective), skills)
            except GroupingError as error:
                raise GroupingError(
                    f"{perspective.value.title()} generation failed: {error} "
                    "Previous groups are unchanged."
                ) from error
            results.append(Grouping(perspective, version, provider.model, groups))
        groupings = tuple(results)
        self.store.save(groupings)
        return groupings

    def explore(self) -> dict[Perspective, GroupingView]:
        snapshot = self.store.read_all()
        saved = {g.perspective: g for g in snapshot.groupings}
        return {p: self._view(GroupingCatalog(snapshot.skills, saved.get(p))) for p in Perspective}

    def browse(
        self, perspective: Perspective, selected_identity: SkillIdentity | None = None
    ) -> GroupingView:
        return self._view(self.store.read(perspective), selected_identity)

    @staticmethod
    def _view(
        data: GroupingCatalog, selected_identity: SkillIdentity | None = None
    ) -> GroupingView:
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
