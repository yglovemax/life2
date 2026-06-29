# Nexa Agent V1 Phase C SSE Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Agent-specific SSE so frontend can render route decisions, tool calls, generated text, recommendations, memory updates, and completion state as separate events.

**Architecture:** Reuse the existing Agent reply orchestration and existing chat SSE security/rate-limit pattern. `generate_agent_reply()` still composes and persists the final answer first; `stream_agent_reply_events()` serializes the completed reply into Agent-specific SSE events.

**Tech Stack:** FastAPI `StreamingResponse`, existing App stream auth, pytest `TestClient.stream`, existing `sse_event` helper.

---

## File Map

- Modify `app/agent.py`: add `stream_agent_reply_events(reply)` to emit `route`, `tool_call`, `delta`, `recommendations`, `memory`, `done`.
- Modify `app/main.py`: add `GET /api/app/agent/sessions/{session_id}/stream`, reusing `require_app_stream_token` and chat rate limit.
- Modify `tests/test_agent_api.py`: add SSE event order and query `api_key` tests.
- Modify `docs/app-api.md` and `docs/frontend-api-contract.md`: document Agent SSE endpoint and events.

## Task 1: Agent Stream Events

**Files:**
- Modify: `app/agent.py`
- Test: `tests/test_agent_api.py`

- [x] **Step 1: Write failing test**

```python
def test_agent_stream_emits_route_tool_delta_recommendations_memory_and_done_events():
    user = create_agent_user()
    agent_session = create_agent_session(user["id"], entry_type="free_question")
    with client.stream(
        "GET",
        f"/api/app/agent/sessions/{agent_session['id']}/stream",
        headers=APP_HEADERS,
        params={"content": "用塔罗看他现在怎么想我？", "simulate_model_response": "先看当下互动。"},
    ) as response:
        assert response.status_code == 200
        body = response.read().decode("utf-8")
    assert "event: route" in body
    assert "event: tool_call" in body
    assert "event: delta" in body
    assert "event: recommendations" in body
    assert "event: memory" in body
    assert "event: done" in body
```

- [x] **Step 2: Run red test**

Run: `.venv/bin/python -m pytest tests/test_agent_api.py::test_agent_stream_emits_route_tool_delta_recommendations_memory_and_done_events -q`

Expected: FAIL because the stream endpoint does not exist.

- [x] **Step 3: Implement endpoint and event serializer**

Event order must be:

```text
route
tool_call
delta
recommendations
memory
done
```

- [x] **Step 4: Verify green**

Run: `.venv/bin/python -m pytest tests/test_agent_api.py -q`

Expected: PASS.

## Task 2: Query Token and Confirmed Route

**Files:**
- Modify: `app/main.py`
- Test: `tests/test_agent_api.py`

- [x] **Step 1: Write failing test**

```python
def test_agent_stream_accepts_query_api_key_and_confirmed_system():
    ...
    params={
      "api_key": "dev-app-token",
      "content": "那就用六爻看",
      "confirmed_system": "liuyao"
    }
    assert '"selected_system": "liuyao"' in body
```

- [x] **Step 2: Run red test**

Expected: FAIL until query parameter mapping exists.

- [x] **Step 3: Map `confirmed_system` and `selected_system` into the Agent payload**

`confirmed_system` becomes:

```json
{"confirmed_route": {"selected_system": "liuyao"}}
```

- [x] **Step 4: Verify green and full suite**

Run: `.venv/bin/python -m pytest -q`

Expected: all tests pass.

## Self-Review

- Spec coverage: covers Agent-specific SSE, event order, query-token support, and route confirmation through query params.
- Placeholder scan: no hidden implementation placeholders.
- Type consistency: events reuse existing Agent reply fields: `route`, `tool_calls`, `answer`, `recommendations`, `memory_updates`, `messages`.
