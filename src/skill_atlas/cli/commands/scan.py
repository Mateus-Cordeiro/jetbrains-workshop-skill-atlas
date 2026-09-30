import sys
from typing import Annotated

import typer
from rich.console import Console
from rich.text import Text

from skill_atlas import runtime
from skill_atlas.cli.output.console import print_result
from skill_atlas.cli.output.tui import ResultsApp
from skill_atlas.config import Settings
from skill_atlas.errors import AtlasError
from skill_atlas.models import Repository


def scan(
    repository_url: Annotated[str, typer.Argument(help="GitHub repository URL to scan.")],
    no_interactive: Annotated[
        bool,
        typer.Option("--no-interactive", help="Print results and exit without opening the UI."),
    ] = False,
) -> None:
    """Discover skills at the default branch and update the local catalog."""
    try:
        repository = Repository.from_url(repository_url)
    except ValueError as error:
        raise typer.BadParameter(str(error), param_hint="repository_url") from error
    try:
        with runtime.create_scanner(Settings.from_environment()) as scanner:
            result = scanner.scan(repository)
    except AtlasError as error:
        Console(stderr=True).print(Text(f"Error: {error}", style="red"))
        raise typer.Exit(code=1) from error

    console = Console()
    if (
        not no_interactive
        and sys.stdin.isatty()
        and console.is_terminal
        and not console.is_dumb_terminal
    ):
        ResultsApp(result).run()
    else:
        print_result(result, console)


def register(app: typer.Typer) -> None:
    app.command(name="scan")(scan)
