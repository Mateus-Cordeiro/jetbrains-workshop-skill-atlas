"""Command registration; application logic belongs in use-case services."""

import typer

from skill_atlas.commands import scan, serve


def create_app() -> typer.Typer:
    app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)

    @app.callback()
    def main() -> None:
        """Discover AI skills and maintain a local catalog."""

    scan.register(app)
    serve.register(app)
    return app


app = create_app()
