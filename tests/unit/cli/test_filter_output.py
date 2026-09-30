from dataclasses import replace
from io import StringIO

import pytest
from rich.console import Console
from rich.text import Text

from skill_atlas.application.catalog import FilteredSkills
from skill_atlas.cli.output.filter import print_filter_result


@pytest.mark.parametrize("width", [40, 160])
@pytest.mark.parametrize("terminal", [False, True])
def test_filter_text_is_literal_safe_and_wraps_without_losing_identity(
    scan_result, width, terminal, monkeypatch
):
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.delenv("NO_COLOR", raising=False)
    skill = replace(
        scan_result.skills[0],
        name="[bold]name[/bold]",
        description="Literal [red]text[/red].\x1b[31m No escape\x07.",
        path="path [red] #?/SKILL.md\x1b]0;malicious title\x07",
    )
    output = StringIO()
    print_filter_result(
        FilteredSkills(1, (skill,)),
        Console(file=output, width=width, force_terminal=terminal),
    )
    text = Text.from_ansi(output.getvalue()).plain
    assert text.splitlines()[0] == "1 matching skill"
    assert "1. [bold]name[/bold]" in text
    assert "Literal [red]text[/red]." in text
    assert "\x07" not in text and "malicious title" not in text
    assert skill.repository.full_name in text
    compact = "".join(text.split())
    assert "path[red]#?/SKILL.md" in compact
    assert skill.url in compact
    assert all(len(line) <= width for line in text.splitlines())
    if not terminal:
        assert "\x1b" not in output.getvalue()
