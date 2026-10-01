"""Shared ownership and revision policy for CLI and Web skill management."""

from pathlib import Path

from skill_atlas.application.documents import MissingSkill, StaleSkill
from skill_atlas.installation import (
    Installation,
    InstallationError,
    InstallationStatus,
    checked_commit,
    hashes,
    source_path,
    target_directory,
)
from skill_atlas.installation_ports import BundleReader, ProjectInstallations
from skill_atlas.models import Repository, Skill
from skill_atlas.ports import CatalogReader


class Installations:
    def __init__(self, catalog: CatalogReader, projects: ProjectInstallations) -> None:
        self.catalog = catalog
        self.projects = projects

    def selection(self, repository: Repository, path: str, commit: str = "") -> Skill:
        source_path(path)
        skill = self.catalog.skill(repository, path)
        if skill is None:
            raise MissingSkill(
                "This skill is no longer in the catalog. Scan its source explicitly."
            )
        checked_commit(skill.commit_sha)
        if commit and skill.commit_sha != commit:
            raise StaleSkill(
                "The catalog changed. Refresh the selection and review its destination."
            )
        return skill

    def preview(
        self,
        project: Path,
        repository: Repository,
        path: str,
        agent: str,
        name: str = "",
        commit: str = "",
    ) -> tuple[Skill, Path]:
        skill = self.selection(repository, path, commit)
        with self.projects.open(project) as session:
            existing = next(
                (r for r in session.records.read() if r.identity == (repository.url, path, agent)),
                None,
            )
            destination = (
                existing.destination if existing else target_directory(agent, name or skill.name)
            )
            if name and destination != target_directory(agent, name):
                raise InstallationError(f"This source is already installed at {destination}.")
        return skill, project / destination

    def list(self, project: Path) -> tuple[InstallationStatus, ...]:
        with self.projects.open(project) as session:
            result = []
            for record in session.records.read():
                skill = self.catalog.skill(
                    Repository.from_url(record.repository_url), record.skill_path
                )
                result.append(
                    InstallationStatus(
                        record,
                        session.files.conflicts(record.destination, record.files),
                        skill.commit_sha if skill else None,
                    )
                )
            return tuple(result)

    def install(
        self,
        project: Path,
        repository: Repository,
        path: str,
        agent: str,
        reader: BundleReader,
        *,
        name: str = "",
        commit: str = "",
        update: bool = False,
        expected_destination: str = "",
    ) -> str:
        skill = self.selection(repository, path, commit)
        with self.projects.open(project) as session:
            records = session.records.read()
            old = next((r for r in records if r.identity == (repository.url, path, agent)), None)
            if update and old is None:
                raise InstallationError("This source is not installed for the selected agent.")
            destination = old.destination if old else target_directory(agent, name or skill.name)
            if name and destination != target_directory(agent, name):
                raise InstallationError(f"This source is already installed at {destination}.")
            if expected_destination and str(project / destination) != expected_destination:
                raise InstallationError("The destination changed. Preview the installation again.")
            if old:
                conflicts = session.files.conflicts(destination, old.files)
                if conflicts:
                    raise InstallationError(
                        "Local changes prevent replacement: " + ", ".join(conflicts)
                    )
                if old.commit_sha == skill.commit_sha:
                    return f"Already installed (unchanged): {project / destination}"
                if not update:
                    raise InstallationError(
                        "A different revision is installed. Use update explicitly."
                    )
            elif any(
                r.destination.casefold() == destination.casefold() for r in records
            ) or session.files.exists(destination):
                raise InstallationError(
                    f"Destination collision: {project / destination}. Choose another name."
                )
            bundle = reader.read_bundle(skill)
            new = Installation(
                repository.url, path, skill.commit_sha, agent, destination, hashes(bundle)
            )
            # Validate again after a potentially slow download; no edits may be discarded.
            if old and (conflicts := session.files.conflicts(destination, old.files)):
                raise InstallationError(
                    "Local changes prevent replacement: " + ", ".join(conflicts)
                )
            session.commit(tuple(r for r in records if r != old) + (new,), old, new, bundle)
        return f"{'Updated' if old else 'Installed'}: {project / destination}"

    def uninstall(
        self,
        project: Path,
        repository: Repository,
        path: str,
        agent: str,
        *,
        expected_commit: str = "",
    ) -> str:
        source_path(path)
        target_directory(agent, "validation")
        with self.projects.open(project) as session:
            records = session.records.read()
            old = next((r for r in records if r.identity == (repository.url, path, agent)), None)
            if old is None:
                raise InstallationError("This source is not installed for the selected agent.")
            if expected_commit and old.commit_sha != expected_commit:
                raise InstallationError("The installation changed. Refresh before uninstalling.")
            conflicts = session.files.conflicts(old.destination, old.files)
            if conflicts:
                raise InstallationError("Local changes prevent uninstall: " + ", ".join(conflicts))
            session.commit(tuple(r for r in records if r != old), old, None, ())
        return f"Uninstalled: {project / old.destination}"
