"""Lossless JSON serialization of catalog matches."""

import json
from typing import TextIO

from skill_atlas.application.catalog import FilteredSkills


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
