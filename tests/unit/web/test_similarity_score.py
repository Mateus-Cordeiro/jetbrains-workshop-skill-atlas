from html.parser import HTMLParser

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape

from skill_atlas.web.app import ASSETS


class MeterParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.meters = []

    def handle_starttag(self, tag, attrs):
        if tag == "meter":
            self.meters.append(dict(attrs))


@pytest.mark.parametrize(
    ("score", "band"),
    [(0, "low"), (39, "low"), (40, "medium"), (69, "medium"), (70, "high"), (100, "high")],
)
def test_similarity_meter_range_value_and_colour_boundaries(score, band):
    templates = Environment(
        loader=FileSystemLoader(ASSETS / "templates"), autoescape=select_autoescape()
    )
    html = templates.get_template("fragments/similarity-score.html").render(
        score=score, name="<script>example</script>"
    )
    parser = MeterParser()
    parser.feed(html)
    (meter,) = parser.meters
    assert meter["min"] == "0" and meter["max"] == "100"
    assert meter["value"] == str(score)
    assert meter["aria-valuetext"] == f"{score}% similarity"
    assert f"score-{band}" in meter["class"].split()
    assert f"<span>{score}%</span>" in html
    assert "<script>" not in html
