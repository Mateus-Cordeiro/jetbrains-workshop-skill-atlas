"""Scan use case: coordinate ports without depending on their implementations."""

from skill_atlas.models import Repository, ScanResult, Skill, Snapshot
from skill_atlas.ports import Catalog, RepositoryReader, SkillParser


class Scanner:
    def __init__(self, reader: RepositoryReader, parser: SkillParser, catalog: Catalog) -> None:
        self.reader = reader
        self.parser = parser
        self.catalog = catalog

    def scan(self, repository: Repository) -> ScanResult:
        return self.scan_snapshot(self.reader.resolve(repository))

    def scan_snapshot(self, snapshot: Snapshot) -> ScanResult:
        """Scan an already resolved snapshot without resolving its branch again."""
        skills = []
        for file in self.reader.skill_files(snapshot):
            metadata = self.parser.parse(self.reader.read_file(snapshot, file))
            if metadata is not None:
                skills.append(
                    Skill(
                        repository=snapshot.repository,
                        path=file.path,
                        name=metadata.name,
                        description=metadata.description,
                        commit_sha=snapshot.commit_sha,
                    )
                )
        result = ScanResult(
            repository=snapshot.repository,
            commit_sha=snapshot.commit_sha,
            skills=tuple(sorted(skills, key=lambda skill: (skill.name, skill.path))),
        )
        # No catalog mutation occurs until the complete remote snapshot is read.
        self.catalog.replace_repository(result)
        return result
