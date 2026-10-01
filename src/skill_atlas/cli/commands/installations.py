"""CLI adaptation for shared project installation services."""

import json
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

import typer

from skill_atlas import runtime
from skill_atlas.adapters.projects import project_path
from skill_atlas.cli.output.text import display_text
from skill_atlas.config import Settings
from skill_atlas.errors import AtlasError
from skill_atlas.models import Repository

ProjectOption = Annotated[
    Path | None, typer.Option(help="Project directory; defaults to the current Git root.")
]
AgentOption = Annotated[str, typer.Option(help="Target agent: codex or claude.")]


def _change(
    action: str,
    repository_url: str,
    skill_path: str,
    project: Path | None,
    agent: str,
    name: str = "",
) -> None:
    try:
        repository = Repository.from_url(repository_url)
        root = project_path(project)
        settings = Settings.from_environment()
        service = runtime.create_installations(settings)
        if action == "uninstall":
            message = service.uninstall(root, repository, skill_path, agent)
        else:
            message = service.install(
                root,
                repository,
                skill_path,
                agent,
                runtime.LazyBundleReader(settings),
                name=name,
                update=action == "update",
            )
        typer.echo(display_text(message))
    except (AtlasError, ValueError) as error:
        typer.echo("Error: " + display_text(str(error)), err=True)
        raise typer.Exit(1) from error


def install(
    repository_url: str,
    skill_path: str,
    *,
    agent: AgentOption,
    project: ProjectOption = None,
    name: str = "",
) -> None:
    """Copy the catalog's recorded skill bundle into a project."""
    _change("install", repository_url, skill_path, project, agent, name)


def update(
    repository_url: str, skill_path: str, *, agent: AgentOption, project: ProjectOption = None
) -> None:
    """Replace an unmodified installation with the latest scanned revision."""
    _change("update", repository_url, skill_path, project, agent)


def uninstall(
    repository_url: str, skill_path: str, *, agent: AgentOption, project: ProjectOption = None
) -> None:
    """Remove an unmodified owned installation, without network access."""
    _change("uninstall", repository_url, skill_path, project, agent)


def installed(
    project: ProjectOption = None, json_output: Annotated[bool, typer.Option("--json")] = False
) -> None:
    """List installation status, recorded revisions, and conflicting paths offline."""
    try:
        root = project_path(project)
        statuses = runtime.create_installations(Settings.from_environment()).list(root)
        if json_output:
            typer.echo(json.dumps([dict(asdict(s), state=s.state) for s in statuses]))
        elif not statuses:
            typer.echo("No skills installed in this project.")
        else:
            for status in statuses:
                record = status.installation
                typer.echo(
                    display_text(
                        f"{record.agent} · {root / record.destination} · {status.state}\n"
                        f"  {record.repository_url} · {record.skill_path} · {record.commit_sha}"
                    )
                )
                for conflict in status.conflicts:
                    typer.echo(display_text(f"  Conflict: {conflict}"))
    except AtlasError as error:
        typer.echo("Error: " + display_text(str(error)), err=True)
        raise typer.Exit(1) from error


def register(app: typer.Typer) -> None:
    for command in (install, installed, update, uninstall):
        app.command()(command)
    app.command("status")(installed)
