import sys
from typing import Annotated

import typer
from rich.console import Console
from rich.text import Text

from skill_atlas import runtime
from skill_atlas.application.organization_scan import OrganizationProgress
from skill_atlas.cli.output.organization import print_organization_summary
from skill_atlas.cli.output.presentation import show_results
from skill_atlas.cli.output.results import scan_view
from skill_atlas.config import Settings
from skill_atlas.errors import AtlasError
from skill_atlas.models import Organization, scan_target


def _fail(error: AtlasError | str) -> typer.Exit:
    Console(stderr=True).print(Text(f"Error: {error}", style="red"))
    return typer.Exit(code=1)


def _scan_organization(organization: Organization) -> None:
    errors = Console(stderr=True)
    # Transient progress appears only on an interactive standard error stream.
    status = (
        errors.status("Listing repositories…")
        if errors.is_terminal and not errors.is_dumb_terminal
        else None
    )

    def progress(update: OrganizationProgress) -> None:
        if status is not None:
            status.update(f"Scanning {update.finished} of {update.total} repositories…")

    try:
        if status is not None:
            status.start()
        with runtime.create_organization_scanner(Settings.from_environment()) as scanner:
            result = scanner.scan(organization, progress=progress)
    except AtlasError as error:
        raise _fail(error) from error
    finally:
        if status is not None:
            status.stop()

    print_organization_summary(result, Console(force_terminal=sys.stdout.isatty()))
    if result.problem:
        raise _fail(result.problem)


def scan(
    repository_url: Annotated[
        str,
        typer.Argument(
            help="GitHub repository URL, or organization URL to scan all its repositories."
        ),
    ],
    no_interactive: Annotated[
        bool,
        typer.Option("--no-interactive", help="Print results and exit without opening the UI."),
    ] = False,
) -> None:
    """Discover skills at the default branch and update the local catalog."""
    try:
        target = scan_target(repository_url)
    except ValueError as error:
        raise typer.BadParameter(str(error), param_hint="repository_url") from error
    if isinstance(target, Organization):
        _scan_organization(target)
        return
    try:
        with runtime.create_scanner(Settings.from_environment()) as scanner:
            result = scanner.scan(target)
    except AtlasError as error:
        raise _fail(error) from error

    show_results(scan_view(result), no_interactive=no_interactive)


def register(app: typer.Typer) -> None:
    app.command(name="scan")(scan)
