"""Adapt local star changes for a catalog identity to terminal output."""

from typing import Annotated

import typer
from rich.console import Console
from rich.text import Text

from skill_atlas import runtime
from skill_atlas.application.stars import MissingStarredSkill
from skill_atlas.cli.output.text import display_text, location_text
from skill_atlas.config import Settings
from skill_atlas.errors import AtlasError
from skill_atlas.models import Repository

RepositoryArgument = Annotated[str, typer.Argument(help="GitHub repository URL already scanned.")]
PathArgument = Annotated[
    str, typer.Argument(help="Exact repository-relative path to the catalog skill's SKILL.md.")
]


def _set_star(repository_url: str, skill_path: str, starred: bool) -> None:
    try:
        repository = Repository.from_url(repository_url)
    except ValueError as error:
        raise typer.BadParameter(str(error), param_hint="repository_url") from error
    if not skill_path:
        raise typer.BadParameter("Provide an exact catalog skill path.", param_hint="skill_path")
    try:
        skill = runtime.create_stars(Settings.from_environment()).set(
            repository, skill_path, starred
        )
    except AtlasError as error:
        message = (
            "Skill not found in the catalog. Check its repository and exact path, "
            "or run skill-atlas scan for that repository first."
            if isinstance(error, MissingStarredSkill)
            else str(error)
        )
        Console(stderr=True).print(Text(f"Error: {message}", style="red"))
        raise typer.Exit(code=1) from error
    action = "Starred" if starred else "Unstarred"
    typer.echo(f"{action} {display_text(skill.name, single_line=True)} · {location_text(skill)}")


def star(repository_url: RepositoryArgument, skill_path: PathArgument) -> None:
    """Star a catalog skill locally; starring an already starred skill succeeds."""
    _set_star(repository_url, skill_path, True)


def unstar(repository_url: RepositoryArgument, skill_path: PathArgument) -> None:
    """Remove a local star; unstarring a skill without a star succeeds."""
    _set_star(repository_url, skill_path, False)


def register(app: typer.Typer) -> None:
    app.command()(star)
    app.command()(unstar)
