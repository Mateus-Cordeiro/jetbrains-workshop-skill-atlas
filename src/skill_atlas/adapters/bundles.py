"""Commit-pinned bundle retrieval through the existing authenticated readers."""

from pathlib import PurePosixPath

from skill_atlas.adapters.git import GitSnapshotReader
from skill_atlas.adapters.github import GitHubReader
from skill_atlas.errors import IncompleteListingError
from skill_atlas.installation import (
    BundleFile,
    InstallationError,
    hashes,
    relative_path,
    source_path,
)
from skill_atlas.models import Skill, SkillFile


class RepositoryBundles:
    def __init__(self, github: GitHubReader, git: GitSnapshotReader) -> None:
        self.github = github
        self.git = git

    def read_bundle(self, skill: Skill) -> tuple[BundleFile, ...]:
        source_path(skill.path)
        snapshot = self.github.resolve_commit(skill.repository, skill.commit_sha)
        reader: GitHubReader | GitSnapshotReader = self.github
        try:
            entries = reader.regular_files(snapshot)
        except IncompleteListingError:
            reader = self.git
            entries = reader.regular_files(snapshot)
        root = PurePosixPath(skill.path).parent
        bundle: list[BundleFile] = []
        total = 0
        for entry in entries:
            relative_path(entry.path)
            path = PurePosixPath(entry.path)
            if not path.is_relative_to(root):
                continue
            relative = str(path.relative_to(root))
            content = reader.read_file(snapshot, SkillFile(entry.path, entry.blob_sha))
            total += len(content)
            if len(bundle) >= 10000 or total > 128 * 1024 * 1024:
                raise InstallationError("The bundle exceeds 10,000 files or 128 MiB.")
            bundle.append(BundleFile(relative, content, entry.executable))
        result = tuple(bundle)
        hashes(result)
        return result
