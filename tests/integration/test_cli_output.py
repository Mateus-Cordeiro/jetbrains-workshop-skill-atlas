from dataclasses import replace
from io import StringIO

import pytest
from rich.console import Console
from textual.containers import VerticalScroll
from textual.widgets import Button, Link, Static

from skill_atlas.application.catalog import FilteredSkills
from skill_atlas.application.similarity import SimilarityResult, SimilarMatch
from skill_atlas.cli.output.console import print_result
from skill_atlas.cli.output.results import filter_view, scan_view, similarity_view
from skill_atlas.cli.output.tui import ResultsApp


def test_plain_output_preserves_literal_markup_and_removes_control_sequences(scan_result):
    skill = replace(
        scan_result.skills[0],
        name="[bold]name[/bold]",
        description="Literal [red]text[/red].\x1b[31m No escape\x07.",
    )
    result = replace(scan_result, skills=(skill,))
    output = StringIO()
    print_result(scan_view(result), Console(file=output, width=160, force_terminal=False))
    text = output.getvalue()
    assert "[bold]name[/bold]" in text
    assert "[red]text[/red]" in text
    assert "\x1b" not in text
    assert "\x07" not in text
    assert skill.url in text


@pytest.fixture(params=["scan", "filter", "similar"])
def results_view(scan_result, request):
    if request.param == "scan":
        return scan_view(scan_result)
    if request.param == "filter":
        return filter_view(FilteredSkills(2, scan_result.skills))
    return similarity_view(
        SimilarityResult(
            replace(scan_result.skills[0], path="source/SKILL.md"),
            (
                SimilarMatch(
                    (
                        scan_result.skills[0],
                        replace(scan_result.skills[0], path="copy #?/SKILL.md"),
                    ),
                    82.5,
                ),
                SimilarMatch((scan_result.skills[1],), 20),
            ),
        )
    )


@pytest.mark.parametrize("size", [(120, 30), (40, 20)])
async def test_interactive_toggle_keyboard_button_and_links(results_view, monkeypatch, size):
    app = ResultsApp(results_view)
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
        expected = results_view.source or results_view.entries[0].skill
        assert opened == [expected.url]
        links = list(app.query(Link))
        expected_locations = ([results_view.source] if results_view.source else []) + [
            skill for entry in results_view.entries for skill in entry.locations
        ]
        assert [link.url for link in links] == [skill.url for skill in expected_locations]
        assert len(app.query(".description")) == len(results_view.entries)
        for widget, entry in zip(app.query(".description"), results_view.entries, strict=True):
            assert str(widget.render()) == entry.skill.description
        if results_view.source:
            assert "83%" in str(app.query(".skill-heading").first().render())
            assert "Same metadata · 2 locations" in str(
                app.query_one(".group-label", Static).render()
            )
        links[-1].focus()
        # Let deferred focus scrolling start before waiting for its animation.
        await pilot.pause()
        await pilot.wait_for_scheduled_animations()
        scroll = app.query_one("#skills", VerticalScroll)
        assert links[-1].region.bottom <= scroll.region.bottom
        assert links[-1].region.y >= scroll.region.y
        await pilot.press("q")


async def test_empty_results_remain_usable(results_view):
    app = ResultsApp(replace(results_view, entries=()))
    async with app.run_test() as pilot:
        assert str(app.query_one("#empty", Static).render()) == results_view.empty_message
        await pilot.press("d")
        await pilot.press("q")


async def test_interactive_metadata_is_literal_and_wraps(scan_result, monkeypatch):
    skill = replace(
        scan_result.skills[0],
        name="[red]" + "long-name-" * 8 + "[/red]\x1b[31m",
        description="[bold]Literal description[/bold]\x07\n" + "details " * 30,
        path="[red]long path with spaces[/red]/SKILL.md\x1b]0;title\x07",
    )
    app = ResultsApp(scan_view(replace(scan_result, skills=(skill,))))
    opened = []
    monkeypatch.setattr(app, "open_url", opened.append)
    async with app.run_test(size=(40, 20)) as pilot:
        heading = app.query_one(".skill-heading", Static)
        description = app.query_one(".description", Static)
        location = app.query_one(".location", Static)
        assert "[red]" in str(heading.render())
        assert "[bold]Literal description[/bold]" in str(description.render())
        assert "[red]long path with spaces[/red]/SKILL.md" in str(location.render())
        assert "\x1b" not in str(heading.render()) and "\x07" not in str(description.render())
        assert "title" not in str(location.render())
        for widget in (heading, description, location):
            assert widget.region.height > 1
            assert widget.region.right <= 40
        link = app.query_one(Link)
        assert link.url == skill.url
        link.focus()
        # Let deferred focus scrolling start before waiting for its animation.
        await pilot.pause()
        await pilot.wait_for_scheduled_animations()
        assert link.region.bottom <= app.query_one("#skills").region.bottom
        await pilot.press("enter")
        assert opened == [skill.url]
        await pilot.press("q")
