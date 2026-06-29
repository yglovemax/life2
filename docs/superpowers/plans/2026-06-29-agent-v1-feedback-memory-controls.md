# Nexa Agent V1 Feedback and Memory Controls Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Agent feedback capture and user-controlled memory settings/deletion APIs for frontend integration.

**Architecture:** Keep V1 changes narrow. Feedback gets a dedicated `agent_feedback` table because it is product analytics data. Memory settings live in `AppUser.profile.memory_settings` for this phase to avoid an unnecessary migration-heavy settings table.

**Tech Stack:** FastAPI, SQLAlchemy ORM, existing App token auth, pytest.

---

## File Map

- Modify `app/models.py`: add `AgentFeedback`.
- Modify `app/services.py`: add feedback recording, memory item deletion, memory settings serialization/update, and memory-context switch.
- Modify `app/agent.py`: respect user memory settings in Agent replies.
- Modify `app/main.py`: add feedback, memory delete, and memory settings endpoints.
- Modify `tests/test_agent_api.py`: cover feedback and Agent memory settings behavior.
- Modify `tests/test_app_user_backend_api.py`: cover memory delete and memory settings read/write.
- Modify docs: update API contract and feature catalog.

## Task 1: Feedback API

- [x] Write failing tests for `POST /api/app/agent/messages/{message_id}/feedback`.
- [x] Add `AgentFeedback` model.
- [x] Implement `record_agent_message_feedback`.
- [x] Add FastAPI endpoint.
- [x] Verify feedback tests pass.

## Task 2: Memory Controls

- [x] Write failing tests for memory deletion and memory settings.
- [x] Implement soft-delete for memory items.
- [x] Implement `GET/PUT /api/app/users/{user_id}/memory-settings`.
- [x] Respect memory settings in Agent replies.
- [x] Verify memory-control tests pass.

## Task 3: Docs and Full Verification

- [x] Document new endpoints for frontend team.
- [x] Run focused tests.
- [x] Run full pytest.
- [x] Commit and push.
