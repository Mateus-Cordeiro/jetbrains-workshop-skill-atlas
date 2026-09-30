from dataclasses import replace
from io import StringIO

import pytest
from rich.console import Console
from rich.text import Text

from skill_atlas.application.catalog import FilteredSkills
from skill_atlas.application.similarity import SimilarityResult, SimilarMatch
from skill_atlas.cli.output.console import print_result
from skill_atlas.cli.output.results import filter_view, scan_view, similarity_view


@pytest.mark.parametrize("width", [40, 160])
@pytest.mark.parametrize("terminal", [False, True])
def test_all_commands_share_entry_layout_and_visible_links(
    scan_result, width, terminal, monkeypatch
):
    monkeypatch.setenv("TERM_PROGRAM", "iTerm.app")
    monkeypatch.setenv("TERM", "xterm-256color")
    skill = replace(scan_result.skills[0], path="review #?/SKILL.md")
    views = (
        scan_view(replace(scan_result, skills=(skill,))),
        filter_view(FilteredSkills(1, (skill,))),
        similarity_view(
            SimilarityResult(replace(skill, path="source/SKILL.md"), (SimilarMatch((skill,), 80),))
        ),
    )
    entries = []
    for view in views:
        output = StringIO()
        print_result(view, Console(file=output, width=width, force_terminal=terminal))
        raw = output.getvalue()
        text = Text.from_ansi(raw).plain
        entry = text[text.index("1. code-review") :]
        assert skill.url in "".join(entry.split())
        assert all(len(line) <= width for line in text.splitlines())
        assert entry.index("Review code") < entry.index("Acme/skills") < entry.index("https://")
        if terminal:
            assert "\x1b]8;" in raw  # supported terminals retain clickable URLs
        else:
            assert "\x1b" not in raw
        entries.append(entry.replace(" · 80%", ""))
    assert entries[0] == entries[1] == entries[2]
