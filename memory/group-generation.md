# Group generation debugging

Last verified: 2026-10-01.

## Coverage needs a schema constraint

The former group-centric Ollama response schema permitted omissions even though
the prompt required every skill. Local Qwen reproduced a Capabilities failure
with 44 groups for 45 inputs and one missing ID; Topics passed. The shared
validator correctly rejected it, but its generic error hid the reason. This
failure predated graph rendering and was independent of browser presentation.

The [adapter](../src/skill_atlas/adapters/ollama.py) now requests numbered titles
and a required assignment key for every skill, then translates to the existing
application format. Local generation on the same snapshot produced 10 capability
groups and 8 topic groups, covering all 45 inputs. Unused proposed titles can occur
even with required assignments; discard them before publication without changing
memberships. These observed counts are examples, not a stable taxonomy. The
[feature spec](../spec/features/skill-groups.md) owns the limit and validation policy.

To investigate a live failure, read `/explore/status`, then call the provider and
validator against one read-only catalog snapshot, without calling the saving
service. Summarize counts and invalid opaque IDs rather than recording private
metadata or model output. Saved jobs contain sanitized errors, not raw responses.

Ollama's `format` schema constrains decoding rather than adding prompt text. Count
messages, chat-template headroom, and output reservation in the conservative
context guard. Counting a schema property for every skill as prompt text caused
a false context rejection for an otherwise fitting catalog. This was checked
against [Ollama's format handling](https://github.com/ollama/ollama/blob/v0.34.4/llm/llama_server.go).

## Test boundary

The [shared Web fixture](../tests/web_environment.py) accepts group-centric
scenario data and translates it to Ollama's wire format only in the mock HTTP
transport. Missing members stay missing, so integration and browser tests exercise
real assignment validation and atomic publication. Adapter tests supply wire
responses directly; the installed-wheel smoke uses the same wire contract.
Live model checks remain separate from automated tests.

## Optional settings must not break other features

Every CLI command calls `Settings.from_environment()`. Eagerly converting Ollama
values there made a typo such as `10m` break scans, filtering, similarity, and
Web startup with a `ValueError`. Keep those raw values until the explicit
generation callback in [runtime](../src/skill_atlas/runtime.py) parses them.
The [CLI regression](../tests/integration/test_cli.py) exercises all four entry
points with malformed settings; [generation integration tests](../tests/integration/test_grouping_web.py)
verify named-setting errors, no model request, and preservation of saved groups.
