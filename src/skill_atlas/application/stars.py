"""Star catalog identities locally; starring never reads GitHub or rescans."""

from skill_atlas.errors import AtlasError
from skill_atlas.models import Repository, Skill
from skill_atlas.ports import StarWriter


class MissingStarredSkill(AtlasError):
    pass


class Stars:
    def __init__(self, catalog: StarWriter) -> None:
        self.catalog = catalog

    def set(self, repository: Repository, path: str, starred: bool) -> Skill:
        """Idempotently set the star; repeating a request leaves the same state."""
        skill = self.catalog.set_starred(repository, path, starred)
        if skill is None:
            raise MissingStarredSkill("Skill not found in the catalog. Refresh the skill list.")
        return skill
