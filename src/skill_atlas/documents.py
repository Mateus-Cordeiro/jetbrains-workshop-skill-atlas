"""Load a catalog document without changing or rescanning the catalog."""

from dataclasses import dataclass

from skill_atlas.errors import AtlasError, RepositoryError
from skill_atlas.models import Repository, Skill
from skill_atlas.ports import CatalogReader, DocumentReader


class MissingSkill(AtlasError):
    pass


class StaleSkill(AtlasError):
    pass


@dataclass(frozen=True)
class Document:
    skill: Skill
    source: str


class Documents:
    def __init__(self, catalog: CatalogReader, reader: DocumentReader) -> None:
        self.catalog = catalog
        self.reader = reader

    def load(self, repository: Repository, path: str, commit: str) -> Document:
        skill = self.catalog.skill(repository, path)
        if skill is None:
            raise MissingSkill("This skill is no longer in the catalog. Refresh the skill list.")
        if skill.commit_sha != commit:
            raise StaleSkill("The catalog has a newer scan. Refresh the skill list.")
        try:
            source = self.reader.read_document(skill).decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise RepositoryError("The skill document is not valid UTF-8.") from error
        return Document(skill, source)
