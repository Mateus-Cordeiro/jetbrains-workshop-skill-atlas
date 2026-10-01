import json
from dataclasses import replace

import httpx
import pytest

from skill_atlas.adapters.ollama import OllamaGrouping
from skill_atlas.errors import GroupingError
from skill_atlas.grouping import Perspective


@pytest.mark.parametrize(
    "perspective,term",
    [(Perspective.TOPICS, "subject area"), (Perspective.CAPABILITIES, "helps accomplish")],
)
def test_native_request_has_schema_complete_metadata_and_no_credentials(
    scan_result, perspective, term
):
    def respond(request):
        assert request.url == "http://127.0.0.1:11434/api/chat"
        assert "authorization" not in request.headers
        payload = json.loads(request.content)
        assert payload["model"] == "fixture-model"
        assert payload["stream"] is False and payload["think"] is False
        schema = payload["format"]
        assert schema["required"] == ["titles", "assignments"]
        assert schema["properties"]["titles"]["maxItems"] == 12
        assignments = schema["properties"]["assignments"]
        assert assignments["required"] == ["s1", "s2"]
        assert set(assignments["properties"]) == {"s1", "s2"}
        assert assignments["additionalProperties"] is False
        assert schema["$defs"]["membership"]["minItems"] == 1
        assert "at most 12" in payload["messages"][0]["content"]
        assert term in payload["messages"][0]["content"]
        skills = json.loads(payload["messages"][1]["content"])
        assert skills == [
            dict(id=f"s{i}", name=s.name, description=s.description)
            for i, s in enumerate(scan_result.skills, 1)
        ]
        assert "repository_url" not in payload["messages"][1]["content"]
        return httpx.Response(
            200,
            json={
                "done": True,
                "message": {
                    "content": json.dumps(
                        {
                            "titles": ["Unused proposal", "Review code", "Prepare releases"],
                            "assignments": {"s2": [3], "s1": [2, 3]},
                        }
                    )
                },
            },
        )

    with httpx.Client(
        base_url="http://127.0.0.1:11434", transport=httpx.MockTransport(respond)
    ) as client:
        assert OllamaGrouping(client, "fixture-model").group(scan_result.skills, perspective) == {
            "groups": [
                {"title": "Review code", "skill_ids": ["s1"]},
                {"title": "Prepare releases", "skill_ids": ["s2", "s1"]},
            ]
        }


def test_schema_requires_all_45_skills_including_the_previously_omitted_id(scan_result):
    # About 20 KB of metadata still fits the default conservative context budget;
    # the decoding schema is not extra prompt text.
    skills = tuple(
        replace(
            scan_result.skills[0], path=f"skill-{i}/SKILL.md", description="Review changes. " * 27
        )
        for i in range(45)
    )

    def respond(request):
        payload = json.loads(request.content)
        assignments = payload["format"]["properties"]["assignments"]
        expected = [f"s{i}" for i in range(1, 46)]
        assert assignments["required"] == expected
        assert set(assignments["properties"]) == set(expected)
        return httpx.Response(
            200,
            json={
                "done": True,
                "message": {
                    "content": json.dumps(
                        {"titles": ["Review code"], "assignments": dict.fromkeys(expected, [1])}
                    )
                },
            },
        )

    with httpx.Client(
        base_url="http://127.0.0.1", transport=httpx.MockTransport(respond)
    ) as client:
        result = OllamaGrouping(client, "model").group(skills, Perspective.CAPABILITIES)
    assert result == {
        "groups": [{"title": "Review code", "skill_ids": [f"s{i}" for i in range(1, 46)]}]
    }


@pytest.mark.parametrize(
    "payload,message",
    [
        (None, "invalid grouping fields"),
        ({"groups": []}, "invalid grouping fields"),
        ({"titles": [], "assignments": {}}, "between 1 and 12"),
        ({"titles": "bad", "assignments": {}}, "between 1 and 12"),
        ({"titles": [str(i) for i in range(13)], "assignments": {}}, "between 1 and 12"),
        ({"titles": ["Code"], "assignments": []}, "invalid skill assignments"),
        ({"titles": ["Code"], "assignments": {"s1": [1]}}, "missing 1 of 2 skills"),
        (
            {"titles": ["Code"], "assignments": {"s1": [1], "s2": [1], "private": [1]}},
            "0 of 2 skills, 1 unknown IDs",
        ),
        ({"titles": ["Code"], "assignments": {"s1": [], "s2": [1]}}, "empty or invalid"),
        ({"titles": ["Code"], "assignments": {"s1": 1, "s2": [1]}}, "empty or invalid"),
        *[
            (
                {"titles": ["Code"], "assignments": {"s1": [index], "s2": [1]}},
                "nonexistent group",
            )
            for index in (0, 2, True, 1.0, "1", {})
        ],
    ],
)
def test_invalid_assignments_fail_without_exposing_model_content(payload, message, scan_result):
    response = httpx.Response(200, json={"done": True, "message": {"content": json.dumps(payload)}})
    with httpx.Client(
        base_url="http://127.0.0.1", transport=httpx.MockTransport(lambda _: response)
    ) as client:
        with pytest.raises(GroupingError, match=message) as error:
            OllamaGrouping(client, "model").group(scan_result.skills, Perspective.TOPICS)
    assert "private" not in str(error.value)


@pytest.mark.parametrize(
    "response,message",
    [
        (httpx.Response(404, text="private server detail"), "could not find"),
        (httpx.Response(500, text="private server detail"), "could not generate"),
        (httpx.Response(200, text="invalid"), "invalid JSON"),
        (httpx.Response(200, json=[]), "invalid JSON"),
        (httpx.Response(200, json={"done": True}), "invalid JSON"),
        (httpx.Response(200, json={"done": True, "message": {"content": 42}}), "invalid JSON"),
        (httpx.Response(200, json={"done": False}), "did not finish"),
        (httpx.Response(200, json={"done": True, "done_reason": "length"}), "did not finish"),
    ],
)
def test_errors_are_actionable_and_do_not_expose_response(response, message, scan_result):
    with httpx.Client(
        base_url="http://127.0.0.1", transport=httpx.MockTransport(lambda _: response)
    ) as client:
        with pytest.raises(GroupingError, match=message) as error:
            OllamaGrouping(client, "model").group(scan_result.skills, Perspective.TOPICS)
        assert "private server detail" not in str(error.value)


@pytest.mark.parametrize(
    "exception,message", [(httpx.ConnectError, "Could not reach"), (httpx.ReadTimeout, "timed out")]
)
def test_transport_errors(exception, message, scan_result):
    def fail(request):
        raise exception("secret upstream error", request=request)

    with httpx.Client(base_url="http://127.0.0.1", transport=httpx.MockTransport(fail)) as client:
        with pytest.raises(GroupingError, match=message):
            OllamaGrouping(client, "model").group(scan_result.skills, Perspective.TOPICS)


@pytest.mark.parametrize(
    "options,message",
    [
        ({"context": 1000, "output_tokens": 100}, "context budget"),
        ({"context": 10, "output_tokens": 100}, "settings"),
        ({"output_tokens": 0}, "settings"),
        ({"model": ""}, "settings"),
    ],
)
def test_invalid_settings_and_context_overflow_do_not_make_requests(options, message, scan_result):
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: pytest.fail("Unexpected request"))
    ) as client:
        model = options.pop("model", "model")
        with pytest.raises(GroupingError, match=message):
            OllamaGrouping(client, model, **options).group(scan_result.skills, Perspective.TOPICS)
