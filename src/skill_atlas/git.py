"""Temporary, shallow Git snapshots with lazily fetched skill contents."""

import base64
import os
import re
import signal
import subprocess
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from types import TracebackType
from typing import Self

from skill_atlas.errors import RepositoryError
from skill_atlas.models import SkillFile, Snapshot


def _git_environment(token: str | None) -> dict[str, str]:
    # Inherited Git repository overrides could point a subprocess at a user's
    # checkout. Config overrides and credentials apply only to our child process.
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment.update(GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never")
    config = [
        ("core.hooksPath", os.devnull),
        ("credential.helper", ""),
        ("maintenance.auto", "false"),
        ("gc.auto", "0"),
        ("http.https://github.com/.extraheader", ""),
    ]
    if token:
        encoded = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        config.append(("http.https://github.com/.extraheader", f"Authorization: Basic {encoded}"))
    environment["GIT_CONFIG_COUNT"] = str(len(config))
    for index, (key, value) in enumerate(config):
        environment[f"GIT_CONFIG_KEY_{index}"] = key
        environment[f"GIT_CONFIG_VALUE_{index}"] = value
    return environment


def _stop_process(process: subprocess.Popen[bytes]) -> None:
    """Stop Git and its transport helpers before deleting the temporary repo."""
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    elif os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                check=False,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            process.kill()
    else:
        process.kill()
    process.communicate()


class GitSnapshotReader:
    def __init__(
        self, token: str | None, *, timeout: float = 120, temp_root: Path | None = None
    ) -> None:
        self._environment = _git_environment(token)
        self._timeout = timeout
        self._temp_root = temp_root
        self._resources = ExitStack()
        self._repositories: dict[Snapshot, Path] = {}

    def __enter__(self) -> Self:
        self._resources.__enter__()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        try:
            self._resources.close()
        except OSError as error:
            raise RepositoryError("Could not remove the temporary Git repository.") from error
        finally:
            self._repositories.clear()

    def _run(self, repository: Path, *arguments: str) -> bytes:
        command = ["git", "-C", str(repository), *arguments]
        try:
            with subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=self._environment,
                start_new_session=os.name == "posix",
            ) as process:
                try:
                    output, _ = process.communicate(timeout=self._timeout)
                except BaseException:
                    _stop_process(process)
                    raise
                if process.returncode:
                    # Raw Git errors can contain credential-helper output. Keep
                    # credentials out of user-facing errors and process arguments.
                    raise RepositoryError(
                        "Git could not read the repository snapshot. "
                        "Check network access, repository permissions, and your Git installation."
                    )
                return output
        except FileNotFoundError as error:
            raise RepositoryError(
                "Git is required to scan large repositories. Install Git first."
            ) from error
        except subprocess.TimeoutExpired as error:
            raise RepositoryError(
                f"Git timed out after {self._timeout:g} seconds. Check your connection and retry."
            ) from error
        except OSError as error:
            raise RepositoryError("Could not run Git for the temporary repository.") from error

    def _repository(self, snapshot: Snapshot) -> Path:
        if snapshot in self._repositories:
            return self._repositories[snapshot]
        try:
            repository = Path(
                self._resources.enter_context(
                    TemporaryDirectory(prefix="skill-atlas-", dir=self._temp_root)
                )
            )
        except OSError as error:
            raise RepositoryError("Could not create a temporary Git repository.") from error
        self._run(repository, "init", "--bare", "--quiet", "--template=")
        self._run(repository, "remote", "add", "origin", snapshot.repository.url + ".git")
        self._run(repository, "config", "remote.origin.promisor", "true")
        self._run(repository, "config", "remote.origin.partialclonefilter", "blob:none")
        # Fetch the exact API-resolved commit, never the current branch tip.
        self._run(
            repository,
            "fetch",
            "--quiet",
            "--depth=1",
            "--filter=blob:none",
            "--no-tags",
            "--recurse-submodules=no",
            "origin",
            snapshot.commit_sha,
        )
        tree = self._run(repository, "rev-parse", f"{snapshot.commit_sha}^{{tree}}")
        if tree.decode("ascii").strip() != snapshot.tree_sha:
            raise RepositoryError("Git returned a different snapshot than the GitHub API.")
        self._repositories[snapshot] = repository
        return repository

    def skill_files(self, snapshot: Snapshot) -> tuple[SkillFile, ...]:
        repository = self._repository(snapshot)
        listing = self._run(repository, "ls-tree", "-r", "-z", "--full-tree", snapshot.commit_sha)
        files = []
        try:
            for entry in listing.split(b"\0"):
                if not entry:
                    continue
                metadata, path = entry.split(b"\t", 1)
                mode, kind, sha = metadata.split()
                if kind != b"blob" or mode not in (b"100644", b"100755"):
                    continue
                if path.split(b"/")[-1] == b"SKILL.md":
                    if not re.fullmatch(b"[0-9a-f]{40}", sha):
                        raise ValueError("Invalid blob SHA")
                    files.append(SkillFile(path.decode("utf-8"), sha.decode("ascii")))
        except ValueError as error:
            raise RepositoryError("Git returned an invalid file listing.") from error
        return tuple(files)

    def read_file(self, snapshot: Snapshot, file: SkillFile) -> bytes:
        # Promisor fetches retrieve just the requested blob. No checkout, filters,
        # hooks, or submodule commands are used to read repository file contents.
        return self._run(self._repository(snapshot), "cat-file", "blob", file.blob_sha)
