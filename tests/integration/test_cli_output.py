from dataclasses import replace
from io import StringIO

import pytest
from rich.console import Console
from textual.widgets import Button, Link

from skill_atlas.cli.output.console import print_result
from skill_atlas.cli.output.tui import ResultsApp


def test_plain_output_preserves_literal_markup_and_removes_control_sequences(scan_result):
    skill = replace(
        scan_result.skills[0],
        name="[bold]name[/bold]",
        description="Literal [red]text[/red].\x1b[31m No escape\x07.",
    )
    result = replace(scan_result, skills=(skill,))
    output = StringIO()
    print_result(result, Console(file=output, width=160, force_terminal=False))
    text = output.getvalue()
    assert "[bold]name[/bold]" in text
    assert "[red]text[/red]" in text
    assert "\x1b" not in text
    assert "\x07" not in text
    assert skill.url in text


@pytest.mark.parametrize("size", [(120, 30), (40, 20)])
async def test_interactive_toggle_keyboard_button_and_links(scan_result, monkeypatch, size):
    app = ResultsApp(scan_result)
    opened = []
    monkeypatch.setattr(app, "open_url", opened.append)
    async with app.run_test(size=size) as pilot:
        assert all(widget.display for widget in app.query(".description"))
        headings = list(app.query(".skill-heading"))
        assert headings[0].region.y < headings[1].region.y
        for link in app.query(Link):
            assert link.region.right <= size[0]
            assert link.region.height > 0
        await pilot.click("#toggle-descriptions")
        assert not any(widget.display for widget in app.query(".description"))
        assert str(app.query_one(Button).label) == "Show descriptions"
        await pilot.press("d")
        assert all(widget.display for widget in app.query(".description"))
        await pilot.click(app.query(Link).first())
        assert opened == [scan_result.skills[0].url]
        await pilot.press("q")


async def test_empty_results_remain_usable(scan_result):
    app = ResultsApp(replace(scan_result, skills=()))
    async with app.run_test() as pilot:
        await pilot.press("d")
        await pilot.press("q")
