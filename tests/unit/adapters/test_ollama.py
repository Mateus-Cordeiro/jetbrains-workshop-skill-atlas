import json
from dataclasses import replace

import httpx
import pytest

from skill_atlas.adapters.ollama import OllamaGrouping
from skill_atlas.errors import GroupingError
from skill_atlas.grouping import Perspective


@pytest.fixture
def ollama_transport():
    def transport(handler):
        def respond(request):
            if request.url.path == "/api/version":
                assert request.method == "GET" and "authorization" not in request.headers
                return httpx.Response(200, json={"version": "0.13.0"})
            return handler(request)

        return httpx.MockTransport(respond)

    return transport


@pytest.mark.parametrize(
    "perspective,term",
    [(Perspective.TOPICS, "subject area"), (Perspective.CAPABILITIES, "helps accomplish")],
)
def test_native_request_has_schema_complete_metadata_and_no_credentials(
    scan_result, perspective, term, ollama_transport
):
    def respond(request):
        assert request.url == "http://127.0.0.1:11434/api/chat"
        assert "authorization" not in request.headers
        payload = json.loads(request.content)
        assert payload["model"] == "fixture-model"
        assert payload["stream"] is False and payload["think"] is False
        assert payload["truncate"] is False and payload["shift"] is False
        assert payload["options"] == {"temperature": 0, "num_predict": 8192}
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
        base_url="http://127.0.0.1:11434", transport=ollama_transport(respond)
    ) as client:
        assert OllamaGrouping(client, "fixture-model").group(scan_result.skills, perspective) == {
            "groups": [
                {"title": "Review code", "skill_ids": ["s1"]},
                {"title": "Prepare releases", "skill_ids": ["s2", "s1"]},
            ]
        }


def test_schema_requires_all_45_skills_including_the_previously_omitted_id(
    scan_result, ollama_transport
):
    # Coverage must be encoded for every input, including catalogs with many skills.
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

    with httpx.Client(base_url="http://127.0.0.1", transport=ollama_transport(respond)) as client:
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
def test_invalid_assignments_fail_without_exposing_model_content(
    payload, message, scan_result, ollama_transport
):
    response = httpx.Response(200, json={"done": True, "message": {"content": json.dumps(payload)}})
    with httpx.Client(
        base_url="http://127.0.0.1", transport=ollama_transport(lambda _: response)
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
def test_errors_are_actionable_and_do_not_expose_response(
    response, message, scan_result, ollama_transport
):
    with httpx.Client(
        base_url="http://127.0.0.1", transport=ollama_transport(lambda _: response)
    ) as client:
        with pytest.raises(GroupingError, match=message) as error:
            OllamaGrouping(client, "model").group(scan_result.skills, Perspective.TOPICS)
        assert "private server detail" not in str(error.value)


@pytest.mark.parametrize(
    "exception,message", [(httpx.ConnectError, "Could not reach"), (httpx.ReadTimeout, "timed out")]
)
def test_transport_errors(exception, message, scan_result, ollama_transport):
    def fail(request):
        raise exception("secret upstream error", request=request)

    with httpx.Client(base_url="http://127.0.0.1", transport=ollama_transport(fail)) as client:
        with pytest.raises(GroupingError, match=message):
            OllamaGrouping(client, "model").group(scan_result.skills, Perspective.TOPICS)


@pytest.mark.parametrize(
    "options,message",
    [
        ({"context": 10, "output_tokens": 100}, "settings"),
        ({"output_tokens": 0}, "settings"),
        ({"model": ""}, "settings"),
    ],
)
def test_invalid_settings_do_not_make_requests(options, message, scan_result):
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: pytest.fail("Unexpected request"))
    ) as client:
        model = options.pop("model", "model")
        with pytest.raises(GroupingError, match=message):
            OllamaGrouping(client, model, **options).group(scan_result.skills, Perspective.TOPICS)


@pytest.mark.parametrize("context", [None, 32768])
def test_large_catalog_uses_complete_metadata_without_byte_budget(
    scan_result, ollama_transport, context
):
    skills = tuple(
        replace(scan_result.skills[0], path=f"skill-{i}/SKILL.md", description="安全 review. " * 50)
        for i in range(61)
    )

    def respond(request):
        payload = json.loads(request.content)
        content = payload["messages"][1]["content"]
        assert len(content.encode()) > 32768
        assert json.loads(content) == [
            dict(id=f"s{i}", name=s.name, description=s.description)
            for i, s in enumerate(skills, 1)
        ]
        if context is None:
            assert "num_ctx" not in payload["options"]
        else:
            assert payload["options"]["num_ctx"] == context
        assert payload["truncate"] is False and payload["shift"] is False
        return httpx.Response(
            200,
            json={
                "done": True,
                "message": {
                    "content": json.dumps(
                        {
                            "titles": ["Review code"],
                            "assignments": {f"s{i}": [1] for i in range(1, 62)},
                        }
                    )
                },
            },
        )

    with httpx.Client(base_url="http://127.0.0.1", transport=ollama_transport(respond)) as client:
        result = OllamaGrouping(client, "model", context=context).group(skills, Perspective.TOPICS)
    assert result["groups"][0]["skill_ids"] == [f"s{i}" for i in range(1, 62)]


@pytest.mark.parametrize("version", ["0.13.0", "0.34.4", "1.0.0", "0.13.0+build.1"])
def test_supported_server_checked_once_per_provider(scan_result, version):
    requests = []

    def respond(request):
        requests.append(request.url.path)
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": version})
        return httpx.Response(
            200,
            json={
                "done": True,
                "message": {
                    "content": json.dumps(
                        {"titles": ["Code"], "assignments": {"s1": [1], "s2": [1]}}
                    )
                },
            },
        )

    with httpx.Client(
        base_url="http://127.0.0.1", transport=httpx.MockTransport(respond)
    ) as client:
        provider = OllamaGrouping(client, "model")
        for perspective in Perspective:
            provider.group(scan_result.skills, perspective)
    assert requests == ["/api/version", "/api/chat", "/api/chat"]


@pytest.mark.parametrize(
    "response",
    [
        *[
            httpx.Response(200, json={"version": version})
            for version in ("0.12.99", "0.13.0-rc1", "unknown", "", None, 13)
        ],
        httpx.Response(200, json={}),
        httpx.Response(200, json=[]),
        httpx.Response(200, text="private invalid version"),
        httpx.Response(404, text="private missing endpoint"),
    ],
)
def test_unverified_server_never_receives_catalog(scan_result, response):
    def respond(request):
        assert request.url.path == "/api/version"
        assert request.method == "GET" and not request.content
        return response

    with httpx.Client(
        base_url="http://127.0.0.1", transport=httpx.MockTransport(respond)
    ) as client:
        with pytest.raises(GroupingError, match="Ollama 0.13.0 or newer") as error:
            OllamaGrouping(client, "model").group(scan_result.skills, Perspective.TOPICS)
    assert "private" not in str(error.value)


@pytest.mark.parametrize("status", [400, 500])
@pytest.mark.parametrize(
    "message",
    [
        "the input length exceeds the context length",
        "the prompt is longer than the context length currently available to the model",
        "request (10000 tokens) exceeds the available context size (4096 tokens)",
    ],
)
def test_context_failure_is_actionable_and_sanitized(
    scan_result, ollama_transport, status, message
):
    with httpx.Client(
        base_url="http://127.0.0.1",
        transport=ollama_transport(
            lambda _: httpx.Response(status, json={"error": message + "; private metadata"})
        ),
    ) as client:
        with pytest.raises(GroupingError, match="does not fit Ollama's context window") as error:
            OllamaGrouping(client, "model").group(scan_result.skills, Perspective.TOPICS)
    assert "SKILL_ATLAS_OLLAMA_CONTEXT" in str(error.value)
    assert "private metadata" not in str(error.value)


@pytest.mark.parametrize("payload", [[], {"error": None}, {"error": "private model error"}])
def test_other_provider_errors_do_not_claim_context_overflow(
    scan_result, ollama_transport, payload
):
    with httpx.Client(
        base_url="http://127.0.0.1",
        transport=ollama_transport(lambda _: httpx.Response(400, json=payload)),
    ) as client:
        with pytest.raises(GroupingError, match="could not generate groups"):
            OllamaGrouping(client, "model").group(scan_result.skills, Perspective.TOPICS)
