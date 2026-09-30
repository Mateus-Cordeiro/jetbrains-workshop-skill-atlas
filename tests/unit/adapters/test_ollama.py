import json

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
        assert payload["format"]["properties"]["groups"]["items"]["required"] == [
            "title",
            "skill_ids",
        ]
        assert term in payload["messages"][0]["content"]
        skills = json.loads(payload["messages"][1]["content"])
        assert skills == [
            dict(id=f"s{i}", name=s.name, description=s.description)
            for i, s in enumerate(scan_result.skills, 1)
        ]
        assert "repository_url" not in payload["messages"][1]["content"]
        return httpx.Response(200, json={"done": True, "message": {"content": '{"groups": []}'}})

    with httpx.Client(
        base_url="http://127.0.0.1:11434", transport=httpx.MockTransport(respond)
    ) as client:
        assert OllamaGrouping(client, "fixture-model").group(scan_result.skills, perspective) == {
            "groups": []
        }


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
