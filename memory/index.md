# Shared project memory

Durable project knowledge for Codex and Claude. Read relevant topic notes before
task work; use the [shared-memory skill](../.agents/skills/shared-memory/SKILL.md)
to maintain them.

## Authoritative references

- [Repository instructions](../AGENTS.md): contribution, verification, and delivery.
- [Specification index](../spec/README.md): architecture and feature contracts.
- [Project README](../README.md): installation and usage.

## Topics

- [Terminal UI testing](terminal-ui-testing.md): waiting for Textual scrolling
  before checking widget geometry in headless tests.
- [Browser UI testing](browser-ui-testing.md): starting a homepage scan and
  returning to a workspace before completion, plus controlled-clock settling
  for desktop visual checkpoints, G6/HTMX lifecycle, graph fixtures, and wide-screen
  navigation geometry checks.
- [Group generation](group-generation.md): diagnosing missing assignments,
  Ollama schema/context handling, and fixture wire-format boundaries.
- [Python test suite](python-testing.md): unique test module basenames, and
  deterministic organization scan tests for rate limits, parallel workers, and Ctrl+C.
- [Restricted network validation](restricted-network-validation.md): running the
  locked checks and Python browser tests when wheel, browser, or image downloads
  are blocked, and why visual baselines still need the container.
