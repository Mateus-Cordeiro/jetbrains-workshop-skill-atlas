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

## Context belongs to Ollama

The former UTF-8 byte guard rejected a 61-skill catalog at a 38,145-token budget.
With `num_ctx` omitted, local Qwen processed both full prompts in about 6,318
tokens and produced valid complete memberships. These are observations, not
capacity thresholds. Increasing context was a workaround for a bad estimate.
The [adapter](../src/skill_atlas/adapters/ollama.py) now leaves context selection
to Ollama unless explicitly overridden and uses its tokenizer's size checks.

Both `truncate: false` and `shift: false` matter: disabling input truncation alone
does not prevent the runner from dropping earlier input as generation fills the
context. Verified the flags in [Ollama 0.13.0's chat handler](https://github.com/ollama/ollama/blob/v0.13.0/server/routes.go)
and [runner](https://github.com/ollama/ollama/blob/v0.13.0/runner/ollamarunner/runner.go).
Older servers can ignore unknown request fields, so the version check runs before
sending metadata; schema-required output assignments alone do not prove the model
saw all input. The [feature spec](../spec/features/skill-groups.md) owns the
compatibility and failure policy.

Ollama's `format` schema constrains decoding rather than adding prompt text.
Counting it as prompt text was another source of false size rejections; see
[Ollama's format handling](https://github.com/ollama/ollama/blob/v0.34.4/llm/llama_server.go).

## Test boundary

The [shared Web fixture](../tests/web_environment.py) accepts group-centric
scenario data and translates it to Ollama's wire format only in the mock HTTP
transport. Missing members stay missing, so integration and browser tests exercise
real assignment validation and atomic publication. Adapter tests supply wire
responses directly; the installed-wheel smoke uses the same wire contract.
Live model checks remain separate from automated tests.
The fixture records `/api/version` probes in `grouping_version_requests`, separately
from inference in `grouping_requests`. Version probes must not open the inference
gate or change assertions about the two perspective calls.

## Optional settings must not break other features

Every CLI command calls `Settings.from_environment()`. Eagerly converting Ollama
values there made a typo such as `10m` break scans, filtering, similarity, and
Web startup with a `ValueError`. Keep those raw values until the explicit
generation callback in [runtime](../src/skill_atlas/runtime.py) parses them.
The [CLI regression](../tests/integration/test_cli.py) exercises all four entry
points with malformed settings; [generation integration tests](../tests/integration/test_grouping_web.py)
verify named-setting errors, no model request, and preservation of saved groups.
