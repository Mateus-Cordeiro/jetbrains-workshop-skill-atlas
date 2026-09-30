"""Launch the loopback Web application."""

from typing import Annotated

import typer
import uvicorn

from skill_atlas import runtime
from skill_atlas.config import Settings


def serve(port: Annotated[int, typer.Option(min=1, max=65535)] = 8000) -> None:
    """Browse the catalog and scan repositories in a local Web UI."""
    typer.echo(f"Open http://127.0.0.1:{port} in your browser. Press Ctrl+C to stop.")
    try:
        uvicorn.run(
            runtime.create_web_app(Settings.from_environment()), host="127.0.0.1", port=port
        )
    except OSError as error:
        typer.echo(f"Could not start the Web server: {error.strerror}", err=True)
        raise typer.Exit(1) from error


def register(app: typer.Typer) -> None:
    app.command()(serve)
