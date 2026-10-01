"""Descriptor-relative filesystem operations; never traverse project symlinks."""

import hashlib
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from uuid import uuid4

from skill_atlas.installation import BundleFile, FileHash, InstallationError, relative_path


class ProjectFiles:
    def __init__(self, root: Path) -> None:
        if not root.is_absolute() or ".." in root.parts:
            raise InstallationError("Use an absolute, normalized project directory.")
        if os.name != "posix":
            raise InstallationError("Safe project installation currently requires macOS or Linux.")
        self.fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
        try:
            for part in root.parts[1:]:
                new = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=self.fd)
                os.close(self.fd)
                self.fd = new
        except BaseException:
            os.close(self.fd)
            raise

    def close(self) -> None:
        os.close(self.fd)

    @contextmanager
    def directory(self, path: str, *, create: bool = False) -> Iterator[int]:
        fd = os.dup(self.fd)
        try:
            if path != ".":
                relative_path(path)
                for part in path.split("/"):
                    if create:
                        try:
                            os.mkdir(part, 0o755, dir_fd=fd)
                            os.fsync(fd)
                        except FileExistsError:
                            pass
                    child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                    os.close(fd)
                    fd = child
            yield fd
        finally:
            os.close(fd)

    @contextmanager
    def parent(self, path: str, *, create: bool = False) -> Iterator[tuple[int, str]]:
        relative_path(path)
        p = PurePosixPath(path)
        with self.directory(str(p.parent), create=create) as fd:
            yield fd, p.name

    def exists(self, path: str) -> bool:
        try:
            with self.parent(path) as (fd, name):
                os.stat(name, dir_fd=fd, follow_symlinks=False)
            return True
        except FileNotFoundError:
            return False

    def mkdir(self, path: str) -> None:
        with self.directory(path, create=True):
            pass

    def read(self, path: str) -> bytes:
        with self.parent(path) as (fd, name):
            handle = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            with os.fdopen(handle, "rb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise InstallationError(f"Unsafe file: {path}")
                return stream.read()

    def write(self, path: str, content: bytes, *, executable: bool = False) -> None:
        with self.parent(path, create=True) as (fd, name):
            temporary = f".atlas-{uuid4().hex}"
            try:
                handle = os.open(
                    temporary,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=fd,
                )
                with os.fdopen(handle, "wb") as stream:
                    stream.write(content)
                    stream.flush()
                    os.fchmod(stream.fileno(), 0o755 if executable else 0o644)
                    os.fsync(stream.fileno())
                os.replace(temporary, name, src_dir_fd=fd, dst_dir_fd=fd)
                os.fsync(fd)
            finally:
                try:
                    os.unlink(temporary, dir_fd=fd)
                except FileNotFoundError:
                    pass

    def rename(self, source: str, destination: str) -> None:
        with (
            self.parent(source) as (src, name),
            self.parent(destination, create=True) as (dst, target),
        ):
            if self.exists(destination):
                raise InstallationError(f"Destination collision: {destination}")
            os.rename(name, target, src_dir_fd=src, dst_dir_fd=dst)
            os.fsync(src)
            os.fsync(dst)

    def entries(self, path: str) -> set[str]:
        with self.directory(path) as fd:
            return set(os.listdir(fd))

    def rmdir(self, path: str) -> None:
        with self.parent(path) as (fd, name):
            os.rmdir(name, dir_fd=fd)
            os.fsync(fd)

    def remove(self, path: str) -> None:
        """Remove transaction-owned data through pinned directory descriptors."""
        with self.parent(path) as (fd, name):
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if stat.S_ISDIR(info.st_mode):
                with self.directory(path) as child:
                    for entry in os.listdir(child):
                        self.remove(f"{path}/{entry}")
                os.rmdir(name, dir_fd=fd)
            else:
                os.unlink(name, dir_fd=fd)
            os.fsync(fd)

    def conflicts(
        self, path: str, files: tuple[FileHash, ...], *, partial: bool = False
    ) -> tuple[str, ...]:
        expected = {file.path: file for file in files}
        directories = {str(parent) for file in files for parent in PurePosixPath(file.path).parents}
        found: set[str] = set()
        conflicts: set[str] = set()

        def walk(directory: str, prefix: str = "") -> None:
            with self.directory(directory) as fd:
                for name in os.listdir(fd):
                    relative = prefix + name
                    full = f"{path}/{relative}"
                    info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                    if stat.S_ISDIR(info.st_mode):
                        if relative not in directories:
                            conflicts.add(full)
                        else:
                            walk(full, relative + "/")
                    elif not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                        conflicts.add(full)
                    else:
                        found.add(relative)
                        file = expected.get(relative)
                        if file is None or (
                            hashlib.sha256(self.read(full)).hexdigest() != file.sha256
                            or bool(info.st_mode & 0o111) != file.executable
                        ):
                            conflicts.add(full)

        try:
            walk(path)
        except (OSError, InstallationError):
            conflicts.add(path)
        if not partial:
            conflicts.update(f"{path}/{name}" for name in expected.keys() - found)
        return tuple(sorted(conflicts))

    def stage(self, path: str, bundle: tuple[BundleFile, ...]) -> None:
        self.mkdir(path)
        for file in bundle:
            self.write(f"{path}/{file.path}", file.content, executable=file.executable)
