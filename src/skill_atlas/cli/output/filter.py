"""Terminal-safe text and lossless JSON presentation of catalog matches."""

import json
from typing import TextIO

from rich.console import Console
from rich.padding import Padding
from rich.text import Text

from skill_atlas.application.catalog import FilteredSkills
from skill_atlas.cli.output.text import display_text


def print_filter_result(result: FilteredSkills, console: Console) -> None:
    count = len(result.matches)
    console.print(Text(f"{count} matching {'skill' if count == 1 else 'skills'}", style="bold"))
    if not result.matches:
        console.print(
            "No saved skills in the selected scope"
            if not result.total_count
            else "No skills match the query"
        )
    for index, skill in enumerate(result.matches, start=1):
        console.print()
        console.print(Text(f"{index}. {display_text(skill.name, single_line=True)}", style="bold"))
        for value in (
            f"{skill.repository.full_name} · {display_text(skill.path, single_line=True)}",
            skill.description,
            skill.url,
        ):
            console.print(Padding(Text(display_text(value), overflow="fold"), (0, 0, 0, 3)))


def write_filter_json(result: FilteredSkills, output: TextIO) -> None:
    payload = {
        "matching_count": len(result.matches),
        "skills": [
            {
                "repository_url": skill.repository.url,
                "repository_name": skill.repository.full_name,
                "skill_path": skill.path,
                "skill_name": skill.name,
                "description": skill.description,
                "commit_sha": skill.commit_sha,
                "url": skill.url,
            }
            for skill in result.matches
        ],
    }
    output.write(json.dumps(payload) + "\n")
