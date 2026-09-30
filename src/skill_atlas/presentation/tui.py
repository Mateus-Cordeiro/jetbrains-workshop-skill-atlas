from textual import on
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Footer, Link, Static

from skill_atlas.models import ScanResult
from skill_atlas.presentation.text import display_text, summary


class ResultsApp(App[None]):
    """An interactive view over an already completed, persisted scan."""

    CSS = """
    Screen { padding: 0 2; }
    #summary { height: auto; margin-bottom: 1; text-style: bold; }
    #skills { height: 1fr; }
    .skill { height: auto; margin-bottom: 1; }
    .skill-heading { height: auto; }
    .skill-name { width: 1fr; height: auto; }
    .skill-link { width: 1fr; height: auto; text-align: right; }
    .description { height: auto; padding-left: 3; }
    #toggle-descriptions { margin-top: 1; }
    """
    BINDINGS = [
        ("d", "toggle_descriptions", "Toggle descriptions"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self, result: ScanResult) -> None:
        super().__init__()
        self.result = result
        self.descriptions_visible = True

    def compose(self) -> ComposeResult:
        yield Static(summary(self.result), id="summary", markup=False)
        with VerticalScroll(id="skills"):
            for index, skill in enumerate(self.result.skills, start=1):
                name = display_text(skill.name, single_line=True)
                with Vertical(classes="skill"):
                    with Horizontal(classes="skill-heading"):
                        yield Static(f"{index}. {name}", classes="skill-name", markup=False)
                        yield Link(name, url=skill.url, classes="skill-link")
                    yield Static(
                        display_text(skill.description), classes="description", markup=False
                    )
        yield Button("Hide descriptions", id="toggle-descriptions")
        yield Footer()

    @on(Button.Pressed, "#toggle-descriptions")
    def action_toggle_descriptions(self) -> None:
        self.descriptions_visible = not self.descriptions_visible
        for description in self.query(".description"):
            description.display = self.descriptions_visible
        self.query_one("#toggle-descriptions", Button).label = (
            "Hide descriptions" if self.descriptions_visible else "Show descriptions"
        )
