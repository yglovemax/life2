# Nexa Agent V1 Phase A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first runnable Agent V1 backend loop: entry context, divination routing, confirmation buttons, Agent reply API, and frontend-facing contracts.

**Architecture:** Reuse the existing `ChatSession`, `ChatMessage`, user chart, memory, knowledge, model routing, and SSE chat foundation. Add a focused Agent orchestration layer that stores Agent-specific context in `metadata_json` first, avoiding premature database migrations until trace/reporting needs are proven.

**Tech Stack:** FastAPI, SQLAlchemy, existing `app/services.py` chat services, pytest, static App API docs.

---

## File Map

- Create `app/agent.py`: Agent routing, quick actions, session wrapping, reply wrapping, lightweight tool result contracts.
- Modify `app/main.py`: expose `/api/app/agent/*` endpoints protected by the existing App token.
- Modify `app/services.py`: only if a small shared helper is needed; avoid moving legacy chat logic in Phase A.
- Create `tests/test_agent_api.py`: route priority, session creation, reply metadata, confirmation behavior.
- Modify `docs/app-api.md`: document Agent session, route preview, reply, and response examples.
- Modify `docs/frontend-api-contract.md`: add frontend integration rules for quick actions and route metadata.
- Modify `docs/codebase-guide.md`: note Agent orchestration file and ownership boundary.

## Task 1: Route Preview API

**Files:**
- Create: `app/agent.py`
- Modify: `app/main.py`
- Test: `tests/test_agent_api.py`

- [ ] **Step 1: Write failing tests**

```python
def test_agent_route_preview_respects_user_explicit_system():
    response = client.post(
        "/api/app/agent/route-preview",
        headers=APP_HEADERS,
        json={"content": "只用八字看我今年事业", "entry_type": "free_question"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["route_source"] == "user_explicit"
    assert data["selected_system"] == "bazi"
    assert data["needs_confirmation"] is False


def test_agent_route_preview_requires_confirmation_when_free_question_switches_entry_system():
    response = client.post(
        "/api/app/agent/route-preview",
        headers=APP_HEADERS,
        json={
            "content": "我该不该答应朋友这个具体事情？",
            "entry_type": "free_question",
            "entry_context": {"system": "astrology"},
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["selected_system"] == "astrology"
    assert data["recommended_system"] == "liuyao"
    assert data["needs_confirmation"] is True
    assert data["quick_actions"][0]["value"] == "liuyao"
```

- [ ] **Step 2: Run red test**

Run: `.venv/bin/python -m pytest tests/test_agent_api.py -q`

Expected: FAIL because `/api/app/agent/route-preview` does not exist.

- [ ] **Step 3: Implement minimal router**

Create `app/agent.py` with:

```python
VALID_SYSTEMS = {"astrology", "bazi", "tarot", "liuyao", "synastry", "oracle", "hybrid_transit"}

def preview_agent_route(payload: dict) -> dict:
    ...
```

Rules:
- user explicit beats everything.
- preset question binds entry context system.
- confirmed route beats auto.
- free question auto-matches keywords.
- if auto recommendation differs from entry context, return `needs_confirmation=true` and keep `selected_system` as the current entry system.

- [ ] **Step 4: Verify green**

Run: `.venv/bin/python -m pytest tests/test_agent_api.py -q`

Expected: PASS.

## Task 2: Agent Sessions

**Files:**
- Modify: `app/agent.py`
- Modify: `app/main.py`
- Test: `tests/test_agent_api.py`

- [ ] **Step 1: Write failing test**

```python
def test_agent_session_stores_entry_context_in_metadata():
    user = create_agent_user()
    response = client.post(
        "/api/app/agent/sessions",
        headers=APP_HEADERS,
        json={
            "user_id": user["id"],
            "entry_type": "preset_question",
            "entry_context": {"page_slug": "daily-horoscope", "system": "astrology"},
            "title": "这对我有什么影响？",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["topic"] == "agent"
    assert data["metadata"]["agent"]["entry_type"] == "preset_question"
    assert data["metadata"]["agent"]["entry_context"]["system"] == "astrology"
```

- [ ] **Step 2: Run red test**

Expected: FAIL because session endpoint does not exist.

- [ ] **Step 3: Implement wrapper over `create_chat_session`**

Store:

```json
{
  "agent": {
    "entry_type": "preset_question",
    "entry_context": {},
    "active_system": "astrology",
    "last_route": {}
  }
}
```

- [ ] **Step 4: Verify green**

Run: `.venv/bin/python -m pytest tests/test_agent_api.py -q`

Expected: PASS.

## Task 3: Agent Reply API

**Files:**
- Modify: `app/agent.py`
- Modify: `app/main.py`
- Test: `tests/test_agent_api.py`

- [ ] **Step 1: Write failing tests**

```python
def test_agent_reply_returns_route_metadata_and_message_ids():
    user = create_agent_user()
    agent_session = create_agent_session(user["id"], entry_type="free_question")
    response = client.post(
        f"/api/app/agent/sessions/{agent_session['id']}/reply",
        headers=APP_HEADERS,
        json={"content": "他现在怎么想我？", "simulate_model_response": "更适合先用塔罗看当下状态。"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["route"]["selected_system"] == "tarot"
    assert data["messages"]["user_message_id"]
    assert data["messages"]["assistant_message_id"]
    assert data["tool_calls"][0]["tool_name"] == "tarot_reading"
```

- [ ] **Step 2: Run red test**

Expected: FAIL because reply endpoint does not exist.

- [ ] **Step 3: Implement wrapper over `generate_chat_reply`**

Before calling legacy chat reply:
- compute route.
- inject `agent_route` into `user_message_metadata`.
- set `knowledge_tags` based on route.

After legacy reply:
- attach route to assistant message metadata if possible.
- return Agent-shaped response.

- [ ] **Step 4: Verify green**

Run: `.venv/bin/python -m pytest tests/test_agent_api.py -q`

Expected: PASS.

## Task 4: Documentation

**Files:**
- Modify: `docs/app-api.md`
- Modify: `docs/frontend-api-contract.md`
- Modify: `docs/codebase-guide.md`

- [ ] **Step 1: Add Agent API request/response examples**
- [ ] **Step 2: Add quick action behavior for frontend**
- [ ] **Step 3: Add code ownership notes**
- [ ] **Step 4: Run full tests**

Run: `.venv/bin/python -m pytest -q`

Expected: all tests pass.

## Self-Review

- Spec coverage: Phase A covers session, route preview, reply, confirmation quick actions, entry context, and API docs. Phase B/C/D remain planned for full tools, feedback, memory settings, and backend config.
- Placeholder scan: no TBD/TODO markers are required for this phase.
- Type consistency: `selected_system`, `recommended_system`, `route_source`, `needs_confirmation`, `quick_actions`, `tool_calls`, and `recommendations` match the PRD response vocabulary.
