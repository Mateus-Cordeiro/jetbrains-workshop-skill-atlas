import pytest

from skill_atlas.models import Repository, ScanResult, Skill


@pytest.fixture
def repository():
    return Repository("Acme", "skills")


@pytest.fixture
def scan_result(repository):
    return ScanResult(
        repository,
        "a" * 40,
        (
            Skill(
                repository,
                "review/SKILL.md",
                "code-review",
                "Review code changes for correctness and maintainability.",
                "a" * 40,
            ),
            Skill(
                repository,
                "release notes/SKILL.md",
                "release-notes",
                "Draft release notes from a set of changes.",
                "a" * 40,
            ),
        ),
    )
