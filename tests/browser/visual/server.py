"""Per-test real Web server, controlled over stdin rather than application routes."""

import json
import os
import socket
import sys
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from time import monotonic, sleep

import pytest_socket
import uvicorn

from skill_atlas.models import Repository, ScanResult, Skill
from tests.web_environment import create_web_environment


def catalog_fixture():
    repository = Repository("Acme", "skills")
    commit = "a" * 40
    return ScanResult(
        repository,
        commit,
        (
            Skill(
                repository,
                "review/SKILL.md",
                "code-review",
                "Review code changes for correctness and maintainability. "
                "Check error handling, verify test coverage, and explain concrete improvements. "
                "Keep feedback focused on the changes and their impact on users.",
                commit,
            ),
            Skill(
                repository,
                "release notes/SKILL.md",
                "release-notes",
                "Draft release notes from a set of changes.",
                commit,
            ),
        ),
    )


@contextmanager
def running_server(state):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        server = uvicorn.Server(
            uvicorn.Config(state.app, log_level="warning", timeout_graceful_shutdown=5)
        )
        thread = Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
        thread.start()
        try:
            deadline = monotonic() + 10
            while not server.started and thread.is_alive() and monotonic() < deadline:
                sleep(0.01)
            if not server.started:
                raise RuntimeError("Visual test server failed to start")
            yield f"http://127.0.0.1:{sock.getsockname()[1]}"
        finally:
            state.scan_gate.set()
            state.document_gate.set()
            server.should_exit = True
            thread.join(timeout=10)
            if thread.is_alive():
                raise RuntimeError("Visual test server failed to stop")


def respond(value):
    print(json.dumps(value), flush=True)


def main():
    # The same boundary substitution as pytest; no real credential lookup or sockets.
    os.environ.pop("GH_TOKEN", None)
    os.environ.pop("GITHUB_TOKEN", None)
    pytest_socket.socket_allow_hosts(["127.0.0.1"], allow_unix_socket=True)
    fixture = catalog_fixture()
    with TemporaryDirectory(prefix="skill-atlas-visual-") as directory:
        os.environ["SKILL_ATLAS_DB"] = str(Path(directory) / "catalog.sqlite3")
        with create_web_environment(Path(directory), fixture, gate_timeout=60) as state:
            state.source = (
                "---\nname: code-review\ndescription: Review changes.\n---\n"
                "# Review changes\n\nReview the patch and explain actionable improvements.\n\n"
                "## Checklist\n\n- Check error handling.\n- Verify regression coverage.\n\n"
                "```python\nassert result.is_valid\n```\n"
            )
            state.catalog.replace_repository(fixture)
            other = Repository("other", "tools")
            state.catalog.replace_repository(
                replace(
                    fixture,
                    repository=other,
                    skills=tuple(replace(skill, repository=other) for skill in fixture.skills),
                )
            )
            with running_server(state) as base_url:
                respond({"baseURL": base_url, "catalogPath": str(state.settings.database_path)})
                for line in sys.stdin:
                    message = json.loads(line)
                    command = message["command"]
                    if command == "stop":
                        break
                    if command == "scan":
                        state.scan_status = message["status"]
                        if message["blocked"]:
                            state.scan_gate.clear()
                        else:
                            state.scan_gate.set()
                        respond({"ok": True})
                    elif command == "requests":
                        respond({"paths": [request.url.path for request in state.requests]})
                    else:
                        raise ValueError(f"Unknown visual fixture command: {command}")


if __name__ == "__main__":
    main()
