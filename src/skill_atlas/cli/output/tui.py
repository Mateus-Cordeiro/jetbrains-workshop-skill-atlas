from textual import on
from textual.app import App, ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Button, Footer, Link, Static

from skill_atlas.cli.output.results import ResultsView
from skill_atlas.cli.output.text import display_text, location_text
from skill_atlas.models import Skill


class ResultsApp(App[None]):
    """An interactive view of completed results, without catalog or network access."""

    CSS = """
    Screen { padding: 0 2; }
    #summary { height: auto; margin-bottom: 1; text-style: bold; }
    #skills { height: 1fr; }
    .skill { height: auto; margin-bottom: 1; }
    .skill-heading { height: auto; text-style: bold; }
    .skill-link { width: 1fr; height: auto; margin-left: 3; }
    .description, .location, .group-label { height: auto; padding-left: 3; }
    #guidance { height: auto; margin-bottom: 1; }
    #empty { height: auto; }
    #toggle-descriptions { margin-top: 1; }
    """
    BINDINGS = [
        ("d", "toggle_descriptions", "Toggle descriptions"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self, result: ResultsView) -> None:
        super().__init__()
        self.result = result
        self.descriptions_visible = True

    def compose(self) -> ComposeResult:
        yield Static(display_text(self.result.title, single_line=True), id="summary", markup=False)
        with VerticalScroll(id="skills"):
            if self.result.source is not None:
                yield from self._location(self.result.source)
            if self.result.guidance:
                yield Static(display_text(self.result.guidance), id="guidance", markup=False)
            if not self.result.entries:
                yield Static(self.result.empty_message, id="empty", markup=False)
            for index, entry in enumerate(self.result.entries, start=1):
                with Vertical(classes="skill"):
                    yield Static(
                        display_text(entry.heading(index), single_line=True),
                        classes="skill-heading",
                        markup=False,
                    )
                    yield Static(
                        display_text(entry.skill.description), classes="description", markup=False
                    )
                    if len(entry.locations) > 1:
                        yield Static(
                            f"Same metadata · {len(entry.locations)} locations",
                            classes="group-label",
                            markup=False,
                        )
                    for skill in entry.locations:
                        yield from self._location(skill, entry.location(skill))
        yield Button("Hide descriptions", id="toggle-descriptions")
        yield Footer()

    def _location(self, skill: Skill, label: str = "") -> ComposeResult:
        yield Static(label or location_text(skill), classes="location", markup=False)
        yield Link(skill.url, url=skill.url, classes="skill-link")

    @on(Button.Pressed, "#toggle-descriptions")
    def action_toggle_descriptions(self) -> None:
        self.descriptions_visible = not self.descriptions_visible
        for description in self.query(".description"):
            description.display = self.descriptions_visible
        self.query_one("#toggle-descriptions", Button).label = (
            "Hide descriptions" if self.descriptions_visible else "Show descriptions"
        )
