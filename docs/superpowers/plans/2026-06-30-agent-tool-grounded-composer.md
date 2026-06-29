# Nexa Agent Tool-Grounded Composer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Agent replies use structured tool results as first-class answer grounding.

**Architecture:** Agent routing still runs first. The Agent now builds context, executes tools, passes `agent_tool_calls` into chat generation, and only then creates the assistant reply. Chat model prompts include the structured tool payload, and local mock composition reads the same payload so frontend and tests see tool-grounded copy without requiring a live model.

**Tech Stack:** Existing FastAPI Agent API, `app/agent.py`, `app/services.py`, pytest.

---

## File Map

- Modify `app/agent.py`: execute tools before `generate_chat_reply`, pass them into chat payload.
- Modify `app/services.py`: include `agent_tool_calls` in model request and local mock composer.
- Modify `tests/test_agent_api.py`: add tool-grounded answer assertions.
- Modify docs: API and feature catalog.

## Task 1: Failing Tests

- [x] Add tarot test: reply without `simulate_model_response` includes card names from `tool_calls.output_payload.cards`.
- [x] Add liuyao test: reply without `simulate_model_response` includes `hexagram.name`.
- [x] Run focused tests and confirm they fail before implementation.

## Task 2: Composer

- [x] Execute Agent tools before chat answer generation.
- [x] Pass `agent_tool_calls` into chat payload.
- [x] Add tool results to `build_chat_model_request`.
- [x] Add local mock answer branches for tarot, liuyao, oracle, synastry, and chart tools.
- [x] Keep simulated responses exact for existing tests.
- [x] Run focused tests and confirm they pass.

## Task 3: Docs and Verification

- [x] Document that Agent answer is tool-grounded.
- [x] Run full pytest.
- [x] Run HTTP smoke for tarot answer containing card data.
- [x] Commit and push.
