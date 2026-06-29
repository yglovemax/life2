# Nexa Agent V1 Local Tool Providers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace V1 placeholder tool outputs for tarot, liuyao, oracle, and provided-profile synastry with deterministic local structured providers.

**Architecture:** Keep the external tool contract unchanged: each tool still returns one `tool_call` with `input_payload`, `output_payload`, `raw_structured_result`, `status`, and warnings. Local providers use deterministic hashes from question/user/context so tests and frontend rendering are stable; they are clearly marked as `local_*_provider_v1` and can later be swapped for professional algorithms or third-party APIs.

**Tech Stack:** Python pure functions, existing FastAPI Agent endpoints, pytest.

---

## File Map

- Modify `app/agent_tools.py`: add local tarot, liuyao, oracle, and synastry providers.
- Modify `tests/test_agent_api.py`: update expectations from placeholders to computed structured outputs.
- Modify docs: `docs/app-api.md`, `docs/frontend-api-contract.md`, `docs/feature-catalog.md`.

## Task 1: Tests

- [x] Update registry test to expect `local_provider` for tarot, liuyao, oracle, and synastry when relation profile exists.
- [x] Replace tarot placeholder test with computed card spread assertions.
- [x] Add liuyao computed hexagram assertions.
- [x] Add oracle draw assertions.
- [x] Add synastry provided-profile assertions.
- [x] Run focused tests and confirm they fail before implementation.

## Task 2: Providers

- [x] Add deterministic seed helpers.
- [x] Implement tarot three-card spread provider.
- [x] Implement simplified liuyao six-line provider.
- [x] Implement oracle single-draw provider.
- [x] Implement synastry compatibility provider when both user chart and relation profile exists.
- [x] Run focused tests and confirm they pass.

## Task 3: Docs and Verification

- [x] Update API docs to describe `protocol_status=computed`.
- [x] Run full pytest.
- [x] Run HTTP smoke for tarot and liuyao tool calls.
- [x] Commit and push.
