"""Strict, versioned project manifest serialization, separate from the catalog."""

import json
from dataclasses import asdict
from typing import Any

from skill_atlas.adapters.installation.filesystem import ProjectFiles
from skill_atlas.installation import FileHash, Installation, InstallationError

MANIFEST = ".skill-atlas/installations.json"


def encode(records: tuple[Installation, ...]) -> bytes:
    return (
        json.dumps(
            {"version": 1, "installations": [asdict(r) for r in records]}, indent=2, sort_keys=True
        )
        + "\n"
    ).encode()


def decode(content: bytes) -> tuple[Installation, ...]:
    try:
        data: Any = json.loads(content)
        if (
            set(data) != {"version", "installations"}
            or type(data["version"]) is not int
            or data["version"] != 1
        ):
            raise ValueError("Unsupported manifest version")
        result = []
        identities = set()
        destinations = set()
        for item in data["installations"]:
            files = tuple(FileHash(**f) for f in item["files"])
            if any(type(f.executable) is not bool for f in files):
                raise ValueError("Invalid file mode")
            record = Installation(**{**item, "files": files})
            record.validate()
            if record.identity in identities or record.destination.casefold() in destinations:
                raise ValueError("Duplicate installation")
            identities.add(record.identity)
            destinations.add(record.destination.casefold())
            result.append(record)
        return tuple(result)
    except (ValueError, TypeError, KeyError, AttributeError, InstallationError) as error:
        raise InstallationError(
            "Invalid or unsupported project manifest. Preserve it and restore a backup."
        ) from error


class ProjectRecords:
    def __init__(self, files: ProjectFiles) -> None:
        self.files = files

    def read(self) -> tuple[Installation, ...]:
        return decode(self.files.read(MANIFEST)) if self.files.exists(MANIFEST) else ()

    def write(self, records: tuple[Installation, ...]) -> None:
        content = encode(records)
        decode(content)
        self.files.write(MANIFEST, content)
