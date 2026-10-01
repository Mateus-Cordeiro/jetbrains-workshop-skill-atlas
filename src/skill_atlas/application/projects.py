"""Explicit registered-project selection for the local Web interface."""

from pathlib import Path

from skill_atlas.installation import InstallationError
from skill_atlas.installation_ports import ProjectRegistry


class Projects:
    def __init__(self, registry: ProjectRegistry) -> None:
        self.registry = registry

    def list(self) -> tuple[Path, ...]:
        return self.registry.list()

    def register(self, project: Path) -> None:
        self.registry.register(project)

    def select(self, project: Path) -> Path:
        if project not in self.registry.list():
            raise InstallationError("Register and select this local project before installing.")
        return project
