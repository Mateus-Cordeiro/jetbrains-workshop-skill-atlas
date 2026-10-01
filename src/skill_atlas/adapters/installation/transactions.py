"""Serialized, journaled file/manifest publication with conservative recovery."""

import json
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from time import monotonic, sleep

from skill_atlas.adapters.installation.filesystem import ProjectFiles
from skill_atlas.adapters.installation.records import ProjectRecords, decode, encode
from skill_atlas.installation import BundleFile, Installation, InstallationError
from skill_atlas.installation_ports import InstallationTransaction

STATE = ".skill-atlas"
TRANSACTION = f"{STATE}/transaction"
STAGE = f"{TRANSACTION}/staged"
BACKUP = f"{TRANSACTION}/previous"
JOURNAL = f"{TRANSACTION}/journal.json"


class ProjectTransaction:
    def __init__(self, files: ProjectFiles) -> None:
        self.files = files
        self.records = ProjectRecords(files)

    def _clean(self, path: str, record: Installation, *, partial: bool = False) -> None:
        conflicts = self.files.conflicts(path, record.files, partial=partial)
        if conflicts:
            raise InstallationError(
                "Recovery needs attention; preserve these paths: " + ", ".join(conflicts)
            )

    def recover(self) -> None:
        if not self.files.exists(TRANSACTION):
            return
        if not self.files.exists(JOURNAL):
            if not self.files.entries(TRANSACTION):
                self.files.rmdir(TRANSACTION)
                return
            raise InstallationError(
                "Unrecognized staging directory. Inspect and preserve "
                ".skill-atlas/transaction before removing it manually."
            )
        if self.files.entries(TRANSACTION) - {"staged", "previous", "journal.json"}:
            raise InstallationError("Unexpected recovery files. Preserve .skill-atlas/transaction.")
        try:
            journal = json.loads(self.files.read(JOURNAL))
            if journal["phase"] not in {"staging", "ready"}:
                raise ValueError("Invalid journal phase")
            before = decode(json.dumps(journal["before"]).encode())
            after = decode(json.dumps(journal["after"]).encode())
            removed = [r for r in before if r not in after]
            added = [r for r in after if r not in before]
            if len(removed) > 1 or len(added) > 1 or not (removed or added):
                raise ValueError("Invalid journal changes")
            old = removed[0] if removed else None
            new = added[0] if added else None
            record = old or new
            assert record is not None
            destination = record.destination
            if old and new and (old.identity != new.identity or old.destination != new.destination):
                raise ValueError("Invalid journal identity")
        except (ValueError, KeyError, TypeError) as error:
            raise InstallationError(
                "Invalid recovery journal. Preserve .skill-atlas/transaction for recovery."
            ) from error
        if (new is None and self.files.exists(STAGE)) or (
            old is None and self.files.exists(BACKUP)
        ):
            raise InstallationError("Unexpected recovery bundle. Preserve the transaction.")
        current = self.records.read()
        if journal["phase"] == "staging":
            if current != before or self.files.exists(BACKUP):
                raise InstallationError("Invalid staging recovery. Preserve the transaction.")
            if new and self.files.exists(STAGE):
                conflicts = self.files.conflicts(STAGE, new.files, partial=True)
                if conflicts:
                    raise InstallationError(
                        "Staging recovery needs attention: " + ", ".join(conflicts)
                    )
            self._finish()
            return
        if current == after:
            if new:
                self._clean(destination, new)
            elif self.files.exists(destination):
                raise InstallationError(f"Recovery destination collision: {destination}")
            if old and self.files.exists(BACKUP):
                self._clean(BACKUP, old, partial=True)
            if new and self.files.exists(STAGE):
                self._clean(STAGE, new, partial=True)
        elif current == before:
            if self.files.exists(BACKUP):
                if old is None:
                    raise InstallationError("Unexpected recovery backup. Preserve the transaction.")
                self._clean(BACKUP, old)
                if self.files.exists(destination):
                    if new is None or self.files.exists(STAGE):
                        raise InstallationError(f"Recovery destination collision: {destination}")
                    self._clean(destination, new)
                    self.files.rename(destination, STAGE)
                self.files.rename(BACKUP, destination)
            elif old:
                self._clean(destination, old)
            elif new and self.files.exists(destination):
                if self.files.exists(STAGE):
                    raise InstallationError(f"Recovery destination collision: {destination}")
                self._clean(destination, new)
                self.files.rename(destination, STAGE)
            if new and self.files.exists(STAGE):
                self._clean(STAGE, new, partial=True)
        else:
            raise InstallationError(
                "Manifest changed during recovery. Preserve the transaction and manifest."
            )
        self._finish()

    def _finish(self) -> None:
        # Keep the journal until all bundle cleanup finishes. A killed cleanup is
        # replayable: remaining owned files may be a subset, never modified extras.
        for path in (STAGE, BACKUP):
            if self.files.exists(path):
                self.files.remove(path)
        self.files.remove(JOURNAL)
        self.files.rmdir(TRANSACTION)

    def commit(
        self,
        records: tuple[Installation, ...],
        old: Installation | None,
        new: Installation | None,
        bundle: tuple[BundleFile, ...],
    ) -> None:
        before = self.records.read()
        record = old or new
        assert record is not None
        destination = record.destination
        try:
            self.files.mkdir(TRANSACTION)
            journal = {
                "phase": "staging",
                "before": json.loads(encode(before)),
                "after": json.loads(encode(records)),
            }
            self.files.write(JOURNAL, json.dumps(journal).encode())
            if new:
                self.files.stage(STAGE, bundle)
                self._clean(STAGE, new)
            journal["phase"] = "ready"
            self.files.write(JOURNAL, json.dumps(journal).encode())
            if old:
                self._clean(destination, old)
                self.files.rename(destination, BACKUP)
                # Catch edits made immediately before the rename, without deleting them.
                self._clean(BACKUP, old)
            if new:
                self.files.rename(STAGE, destination)
                self._clean(destination, new)
            self.records.write(records)  # Atomic manifest replacement is the commit point.
        except BaseException:
            if not self.files.exists(JOURNAL):
                self.files.rmdir(TRANSACTION)  # Only an empty directory may be removed.
            else:
                self.recover()
            raise
        self.recover()


class LocalProjects:
    @contextmanager
    def open(self, project: Path) -> Iterator[InstallationTransaction]:
        files = None
        try:
            files = ProjectFiles(project)
            files.mkdir(STATE)
            # flock locks a persistent inode, across both threads and processes.
            import fcntl

            with files.directory(STATE) as fd:
                flags = os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK
                try:
                    handle = os.open("lock", flags | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=fd)
                except FileExistsError:
                    handle = os.open("lock", flags, dir_fd=fd)
            with os.fdopen(handle, "rb") as lock:
                info = os.fstat(lock.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise InstallationError("Unsafe project lock file.")
                deadline = monotonic() + 30
                while True:
                    try:
                        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        if monotonic() >= deadline:
                            raise InstallationError(
                                "Another installation operation is busy. Retry shortly."
                            ) from None
                        sleep(0.05)
                session = ProjectTransaction(files)
                session.recover()
                yield session
        except OSError as error:
            raise InstallationError(
                "Cannot safely access project files. Check permissions, symlinks, "
                "and .skill-atlas recovery state."
            ) from error
        finally:
            if files:
                files.close()
