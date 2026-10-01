"""Commit-pinned bundle retrieval through the existing authenticated readers."""

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
        directory = skill.path.rpartition("/")[0]
        prefix = directory + "/" if directory else ""
        snapshot = self.github.resolve_commit(skill.repository, skill.commit_sha)
        reader: GitHubReader | GitSnapshotReader = self.github
        try:
            entries = reader.regular_files(snapshot)
        except IncompleteListingError:
            reader = self.git
            entries = reader.regular_files(snapshot, prefix=prefix)
        bundle: list[BundleFile] = []
        total = 0
        for entry in entries:
            # Check the raw prefix before validation or path normalization. Unrelated
            # repository filenames do not constrain the selected bundle.
            if not entry.path.startswith(prefix):
                continue
            relative = relative_path(entry.path.removeprefix(prefix))
            content = reader.read_file(snapshot, SkillFile(entry.path, entry.blob_sha))
            total += len(content)
            if len(bundle) >= 10000 or total > 128 * 1024 * 1024:
                raise InstallationError("The bundle exceeds 10,000 files or 128 MiB.")
            bundle.append(BundleFile(relative, content, entry.executable))
        result = tuple(bundle)
        hashes(result)
        return result
