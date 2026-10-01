"""Serialize graph presentation data; memberships come from the grouping service."""

import hashlib
import json
from typing import Any

from skill_atlas.application.grouping import GroupingView
from skill_atlas.grouping import Perspective
from skill_atlas.web.routes import url


def graph_data(views: dict[Perspective, GroupingView]) -> dict[str, Any]:
    perspectives = {}
    for perspective, view in views.items():
        nodes = {}
        groups = []
        for group in view.groups:
            members = []
            for skill in group.skills:
                identity = json.dumps([skill.repository.url, skill.path])
                identifier = "skill-" + hashlib.sha256(identity.encode()).hexdigest()[:24]
                members.append(identifier)
                nodes[identifier] = {
                    "id": identifier,
                    "title": skill.name,
                    "description": skill.description,
                    "repository": skill.repository.full_name,
                    "href": url(
                        "/repository",
                        repository_url=skill.repository.url,
                        skill_path=skill.path,
                        from_explore=perspective.value,
                    ),
                }
            groups.append(
                {
                    "id": "group-"
                    + hashlib.sha256((perspective.value + group.title).encode()).hexdigest()[:24],
                    "title": group.title,
                    "members": members,
                }
            )
        perspectives[perspective.value] = {
            "groups": groups,
            "skills": list(nodes.values()),
            "stale": view.stale,
            "generated": view.grouping is not None,
        }
    return {"perspectives": perspectives}
