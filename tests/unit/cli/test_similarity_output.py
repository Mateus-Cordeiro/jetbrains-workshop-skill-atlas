import json
from dataclasses import replace
from io import StringIO

import pytest
from rich.console import Console

from skill_atlas.application.similarity import SimilarityResult, SimilarMatch
from skill_atlas.cli.output.similarity import print_similarity_result, similarity_json


@pytest.mark.parametrize("width", [40, 240])
def test_text_is_literal_safe_and_shows_every_location(scan_result, width):
    source = replace(scan_result.skills[0], name="[bold]Résumé[/bold]\x1b[31m\x07")
    copy = replace(source, path="[red]copy[/red]\x1b]0;title\x07/SKILL.md")
    other = replace(source, path="nested/SKILL.md")
    result = SimilarityResult(source, (SimilarMatch((copy, other), 82.5),))
    output = StringIO()
    print_similarity_result(result, Console(file=output, width=width, force_terminal=False))
    text = output.getvalue()
    assert "[bold]Résumé[/bold]" in text
    assert "1. 83%" in text
    assert "[red]copy[/red]/SKILL.md" in text
    assert "nested/SKILL.md" in text
    assert "Same metadata · 2 locations" in text
    assert "\x1b" not in text and "\x07" not in text
    assert max(map(len, text.splitlines())) <= width
    if width == 240:
        assert source.url in text and copy.url in text and other.url in text
        assert "1 result group" in text
        assert "not document bodies or quality" in text


def test_json_retains_metadata_precision_and_escapes_controls(scan_result):
    source = replace(scan_result.skills[0], name="Résumé\x1b[31m", description="line 1\nline 2\x07")
    candidate = replace(source, path="copy #?/SKILL.md")
    output = similarity_json(SimilarityResult(source, (SimilarMatch((candidate,), 82.123456),)))
    assert "\x1b" not in output and "\x07" not in output
    data = json.loads(output)
    assert data["source"] == {
        "repository_url": source.repository.url,
        "repository_name": source.repository.full_name,
        "skill_path": source.path,
        "name": source.name,
        "description": source.description,
        "commit_sha": source.commit_sha,
        "url": source.url,
    }
    match = data["matches"][0]
    assert match["score"] == 82.123456 and match["display_score"] == 82
    assert match["locations"] == [
        {**data["source"], "skill_path": candidate.path, "url": candidate.url}
    ]
