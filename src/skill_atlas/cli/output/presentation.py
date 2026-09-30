"""Select the same terminal output mode for every catalog command."""

import sys

from rich.console import Console

from skill_atlas.cli.output.console import print_result
from skill_atlas.cli.output.results import ResultsView
from skill_atlas.cli.output.tui import ResultsApp


def show_results(result: ResultsView, *, no_interactive: bool = False) -> None:
    # Explicit terminal detection also overrides FORCE_COLOR for redirected output.
    console = Console(force_terminal=sys.stdout.isatty())
    if (
        not no_interactive
        and sys.stdin.isatty()
        and console.is_terminal
        and not console.is_dumb_terminal
    ):
        ResultsApp(result).run()
    else:
        print_result(result, console)
