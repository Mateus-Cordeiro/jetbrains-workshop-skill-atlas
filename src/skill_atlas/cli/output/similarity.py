"""Lossless JSON serialization of completed similarity searches."""

import json

from skill_atlas.application.similarity import SimilarityResult
from skill_atlas.models import Skill


def _skill_json(skill: Skill) -> dict[str, str | bool]:
    return {
        "repository_url": skill.repository.url,
        "repository_name": skill.repository.full_name,
        "skill_path": skill.path,
        "name": skill.name,
        "description": skill.description,
        "commit_sha": skill.commit_sha,
        "url": skill.url,
        "starred": skill.starred,
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
