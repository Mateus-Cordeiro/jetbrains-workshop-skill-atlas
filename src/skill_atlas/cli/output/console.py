import os

from rich.console import Console
from rich.padding import Padding
from rich.text import Text

from skill_atlas.cli.output.results import ResultsView
from skill_atlas.cli.output.text import display_text, location_text
from skill_atlas.models import Skill


def supports_hyperlinks(console: Console) -> bool:
    if not console.is_terminal or console.is_dumb_terminal:
        return False
    return bool(
        os.environ.get("TERM_PROGRAM") in {"iTerm.app", "WezTerm", "vscode", "ghostty"}
        or os.environ.get("WT_SESSION")
        or os.environ.get("TERM") == "xterm-kitty"
        or os.environ.get("VTE_VERSION", "").isdigit()
        and int(os.environ["VTE_VERSION"]) >= 5000
    )


def _print_location(skill: Skill, console: Console, links: bool) -> None:
    console.print(Padding(Text(location_text(skill), overflow="fold"), (0, 0, 0, 3)))
    console.print(
        Padding(
            Text(skill.url, style=f"link {skill.url}" if links else "", overflow="fold"),
            (0, 0, 0, 3),
        )
    )


def print_result(result: ResultsView, console: Console) -> None:
    links = supports_hyperlinks(console)
    console.print(Text(display_text(result.title, single_line=True), style="bold"))
    if result.source is not None:
        _print_location(result.source, console, links)
    if result.guidance:
        console.print(Text(display_text(result.guidance)))
    if not result.entries:
        console.print(Text(result.empty_message))
    for index, entry in enumerate(result.entries, start=1):
        console.print()
        console.print(
            Text(
                display_text(entry.heading(index), single_line=True), style="bold", overflow="fold"
            )
        )
        console.print(
            Padding(Text(display_text(entry.skill.description), overflow="fold"), (0, 0, 0, 3))
        )
        if len(entry.locations) > 1:
            console.print(Text(f"   Same metadata · {len(entry.locations)} locations"))
        for skill in entry.locations:
            _print_location(skill, console, links)
