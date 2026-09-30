"""Literal, terminal-safe rendering shared by both output modes."""

import re
import unicodedata

from skill_atlas.models import ScanResult, Skill

_ESCAPES = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")


def display_text(value: str, *, single_line: bool = False) -> str:
    value = _ESCAPES.sub("", value)
    value = "".join(char for char in value if char in "\n\t" or unicodedata.category(char) != "Cc")
    return " ".join(value.split()) if single_line else value


def summary(result: ScanResult) -> str:
    count = len(result.skills)
    return f"{result.repository.full_name} — {count} {'skill' if count == 1 else 'skills'}"


def location_text(skill: Skill) -> str:
    return display_text(f"{skill.repository.full_name} · {skill.path}", single_line=True)
