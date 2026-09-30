import os

from rich.console import Console
from rich.padding import Padding
from rich.table import Table
from rich.text import Text

from skill_atlas.cli.output.text import display_text, summary
from skill_atlas.models import ScanResult


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


def print_result(result: ScanResult, console: Console) -> None:
    links = supports_hyperlinks(console)
    console.print(Text(summary(result), style="bold"))
    for index, skill in enumerate(result.skills, start=1):
        name = display_text(skill.name, single_line=True)
        console.print()
        row = Table.grid(expand=True, padding=(0, 1))
        row.add_column(ratio=1, overflow="fold")
        row.add_column(ratio=1, justify="right", overflow="fold")
        row.add_row(
            Text(f"{index}. {name}"),
            Text(name, style=f"link {skill.url}" if links else ""),
        )
        console.print(row)
        console.print(Padding(Text(display_text(skill.description)), (0, 0, 0, 3)))
        if not links:
            console.print(Padding(Text(skill.url, overflow="fold"), (0, 0, 0, 3)))
