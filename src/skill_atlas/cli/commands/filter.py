"""Adapt catalog queries to terminal and JSON output."""

import sys
from typing import Annotated

import typer
from rich.console import Console
from rich.text import Text

from skill_atlas import runtime
from skill_atlas.cli.output.filter import write_filter_json
from skill_atlas.cli.output.presentation import show_results
from skill_atlas.cli.output.results import filter_view
from skill_atlas.config import Settings
from skill_atlas.errors import AtlasError
from skill_atlas.models import Repository


def filter_catalog(
    query: Annotated[
        str, typer.Argument(help="Match all terms in saved names or descriptions.")
    ] = "",
    repository_url: Annotated[
        str | None,
        typer.Option("--repository", help="Restrict results to this GitHub repository URL."),
    ] = None,
    no_interactive: Annotated[
        bool,
        typer.Option("--no-interactive", help="Print results and exit without opening the UI."),
    ] = False,
    json_output: Annotated[
        bool, typer.Option("--json", help="Write a JSON object with matching_count and skills.")
    ] = False,
) -> None:
    """Filter saved skills offline; omit QUERY to list all skills."""
    try:
        repository = Repository.from_url(repository_url) if repository_url is not None else None
    except ValueError as error:
        raise typer.BadParameter(str(error), param_hint="--repository") from error

    try:
        browser = runtime.create_catalog_browser(Settings.from_environment())
        result = browser.filter(query, repository)
    except AtlasError as error:
        Console(stderr=True).print(Text(f"Error: {error}", style="red"))
        raise typer.Exit(code=1) from error

    if json_output:
        write_filter_json(result, sys.stdout)
    else:
        show_results(filter_view(result), no_interactive=no_interactive)


def register(app: typer.Typer) -> None:
    app.command(name="filter")(filter_catalog)
