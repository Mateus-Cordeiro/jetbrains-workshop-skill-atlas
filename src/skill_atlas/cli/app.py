"""Command registration; application logic belongs in use-case services."""

import typer

from skill_atlas.cli.commands import filter, installations, scan, serve, similar, stars


def create_app() -> typer.Typer:
    app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)

    @app.callback()
    def main() -> None:
        """Discover AI skills and maintain a local catalog."""

    scan.register(app)
    filter.register(app)
    serve.register(app)
    similar.register(app)
    stars.register(app)
    installations.register(app)
    return app


app = create_app()
