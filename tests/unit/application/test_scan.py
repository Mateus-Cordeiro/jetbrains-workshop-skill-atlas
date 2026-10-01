from dataclasses import replace

import pytest

from skill_atlas.adapters.frontmatter import FrontmatterParser
from skill_atlas.application.scan import Scanner
from skill_atlas.errors import RepositoryError
from skill_atlas.models import SkillFile, Snapshot


class MemoryCatalog:
    def __init__(self, result=None, starred=()):
        self.result = result
        self.starred = set(starred)
        self.writes = 0

    def replace_repository(self, result):
        self.result = result
        self.writes += 1
        return replace(
            result,
            skills=tuple(
                replace(skill, starred=skill.path in self.starred) for skill in result.skills
            ),
        )


class FakeReader:
    def resolve(self, repository):
        return Snapshot(repository, "b" * 40, "c" * 40)

    def skill_files(self, snapshot):
        return [SkillFile(path, "d" * 40) for path in ["z/SKILL.md", "a/SKILL.md", "bad/SKILL.md"]]

    def read_file(self, snapshot, file):
        if file.path.startswith("bad"):
            return b"No frontmatter"
        return b"---\nname: same-name\ndescription: Description\n---"


def test_scanner_uses_ports_and_keeps_duplicate_names_at_distinct_paths(repository):
    catalog = MemoryCatalog()
    result = Scanner(FakeReader(), FrontmatterParser(), catalog).scan(repository)
    assert [skill.path for skill in result.skills] == ["a/SKILL.md", "z/SKILL.md"]
    assert all(skill.commit_sha == "b" * 40 for skill in result.skills)
    assert [skill.path for skill in catalog.result.skills] == ["a/SKILL.md", "z/SKILL.md"]
    assert catalog.writes == 1


def test_scanner_returns_stored_result_with_retained_stars(repository):
    catalog = MemoryCatalog(starred={"z/SKILL.md"})
    result = Scanner(FakeReader(), FrontmatterParser(), catalog).scan(repository)
    assert not any(skill.starred for skill in catalog.result.skills)
    assert [(skill.path, skill.starred) for skill in result.skills] == [
        ("a/SKILL.md", False),
        ("z/SKILL.md", True),
    ]


def test_failed_read_never_replaces_catalog(repository, scan_result):
    class FailingReader(FakeReader):
        def read_file(self, snapshot, file):
            if file.path.startswith("a"):
                raise RepositoryError("Download failed")
            return super().read_file(snapshot, file)

    catalog = MemoryCatalog(scan_result)
    with pytest.raises(RepositoryError):
        Scanner(FailingReader(), FrontmatterParser(), catalog).scan(repository)
    assert catalog.result is scan_result
    assert catalog.writes == 0


def test_failure_late_in_listing_never_replaces_catalog(repository, scan_result):
    class IncompleteReader(FakeReader):
        def skill_files(self, snapshot):
            yield SkillFile("a/SKILL.md", "d" * 40)
            raise RepositoryError("Incomplete listing")

    catalog = MemoryCatalog(scan_result)
    with pytest.raises(RepositoryError):
        Scanner(IncompleteReader(), FrontmatterParser(), catalog).scan(repository)
    assert catalog.writes == 0


def test_parsing_policy_can_be_replaced_without_changing_scanner(repository):
    class AlternateParser:
        def parse(self, content):
            parsed = FrontmatterParser().parse(content)
            return replace(parsed, name="custom-rule") if parsed else None

    result = Scanner(FakeReader(), AlternateParser(), MemoryCatalog()).scan(repository)
    assert {skill.name for skill in result.skills} == {"custom-rule"}
