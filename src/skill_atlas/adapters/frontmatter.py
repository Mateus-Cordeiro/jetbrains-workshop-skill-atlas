"""Frontmatter extraction policy, independently replaceable through SkillParser."""

import yaml

from skill_atlas.models import SkillMetadata


class FrontmatterParser:
    def parse(self, content: bytes) -> SkillMetadata | None:
        try:
            lines = content.decode("utf-8-sig").splitlines()
        except UnicodeDecodeError:
            return None
        if not lines or lines[0] != "---":
            return None
        try:
            end = lines.index("---", 1)
        except ValueError:
            return None
        try:
            metadata = yaml.safe_load("\n".join(lines[1:end]))
        except (yaml.YAMLError, RecursionError, ValueError):
            return None
        if not isinstance(metadata, dict):
            return None
        name, description = metadata.get("name"), metadata.get("description")
        if not isinstance(name, str) or not isinstance(description, str):
            return None
        name, description = name.strip(), description.strip()
        if not name or not description:
            return None
        return SkillMetadata(name=name, description=description)
