"""Find alternatives to a catalog skill without remote access."""

from typing import Annotated

import typer
from rich.console import Console
from rich.text import Text

from skill_atlas import runtime
from skill_atlas.application.similarity import MissingSimilaritySource
from skill_atlas.cli.output.similarity import print_similarity_result, similarity_json
from skill_atlas.config import Settings
from skill_atlas.errors import AtlasError
from skill_atlas.models import Repository


def similar(
    repository_url: Annotated[str, typer.Argument(help="GitHub repository URL already scanned.")],
    skill_path: Annotated[
        str, typer.Argument(help="Exact repository-relative path to the catalog skill's SKILL.md.")
    ],
    json_output: Annotated[
        bool, typer.Option("--json", help="Output JSON with scores, metadata, and all locations.")
    ] = False,
) -> None:
    """Find similar skills in the local catalog and print results without rescanning."""
    try:
        repository = Repository.from_url(repository_url)
    except ValueError as error:
        raise typer.BadParameter(str(error), param_hint="repository_url") from error
    if not skill_path:
        raise typer.BadParameter("Provide an exact catalog skill path.", param_hint="skill_path")
    try:
        search = runtime.create_similarity(Settings.from_environment())
        result = search.search(repository, skill_path)
    except AtlasError as error:
        message = (
            "The starting skill is not in the catalog. Check its repository and exact path, "
            "or run skill-atlas scan for that repository first."
            if isinstance(error, MissingSimilaritySource)
            else str(error)
        )
        Console(stderr=True).print(Text(f"Error: {message}", style="red"))
        raise typer.Exit(code=1) from error

    if json_output:
        typer.echo(similarity_json(result))
    else:
        print_similarity_result(result, Console())


def register(app: typer.Typer) -> None:
    app.command()(similar)
