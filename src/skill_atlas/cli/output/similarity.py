"""Terminal and JSON presentation of completed similarity searches."""

import json

from rich.console import Console
from rich.padding import Padding
from rich.text import Text

from skill_atlas.application.similarity import SimilarityResult
from skill_atlas.cli.output.text import display_text
from skill_atlas.models import Skill


def _print_location(skill: Skill, console: Console) -> None:
    location = display_text(f"{skill.repository.full_name}:{skill.path}", single_line=True)
    console.print(Padding(Text(location, overflow="fold"), (0, 0, 0, 3)))
    console.print(Padding(Text(skill.url, overflow="fold"), (0, 0, 0, 3)))


def print_similarity_result(result: SimilarityResult, console: Console) -> None:
    name = display_text(result.source.name, single_line=True)
    count = len(result.matches)
    console.print(Text(f"Similar to {name} — {count} result {'group' if count == 1 else 'groups'}"))
    _print_location(result.source, console)
    console.print(
        Text(
            "Scores compare names and descriptions, not document bodies or quality. "
            "Even 100% does not prove identical instructions. "
            "Scores can change as the catalog grows."
        )
    )
    if not result.matches:
        console.print(Text("No similar skills found."))
    for index, match in enumerate(result.matches, start=1):
        console.print()
        name = display_text(match.skill.name, single_line=True)
        console.print(Text(f"{index}. {match.display_score}%  {name}"))
        if len(match.locations) > 1:
            console.print(Text(f"   Same metadata · {len(match.locations)} locations"))
        for skill in match.locations:
            _print_location(skill, console)


def _skill_json(skill: Skill) -> dict[str, str]:
    return {
        "repository_url": skill.repository.url,
        "repository_name": skill.repository.full_name,
        "skill_path": skill.path,
        "name": skill.name,
        "description": skill.description,
        "commit_sha": skill.commit_sha,
        "url": skill.url,
    }


def similarity_json(result: SimilarityResult) -> str:
    return json.dumps(
        {
            "source": _skill_json(result.source),
            "matches": [
                {
                    "score": match.score,
                    "display_score": match.display_score,
                    "locations": [_skill_json(skill) for skill in match.locations],
                }
                for match in result.matches
            ],
        },
        indent=2,
        allow_nan=False,
    )
