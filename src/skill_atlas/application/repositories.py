"""Explicit removal of a repository's local catalog entries."""

from skill_atlas.models import Repository
from skill_atlas.ports import RepositoryRemover


class RemoveRepository:
    def __init__(self, catalog: RepositoryRemover) -> None:
        self.catalog = catalog

    def remove(self, repository: Repository) -> None:
        """Idempotently remove stored skills and their stars, without remote requests."""
        self.catalog.remove_repository(repository)
