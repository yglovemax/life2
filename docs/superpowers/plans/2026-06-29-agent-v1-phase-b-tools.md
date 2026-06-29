# Nexa Agent V1 Phase B Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade Agent `tool_calls` from static protocol placeholders into a real tool registry and context-aware execution layer.

**Architecture:** Keep `app/agent.py` focused on routing, sessions, reply wrapping, and recommendations. Add `app/agent_tools.py` as the tool registry and execution boundary, where each selected divination system returns a consistent tool-call object using existing chart context or V1 provider placeholders.

**Tech Stack:** FastAPI App API, existing chat context from `generate_chat_reply`, pure Python tool registry, pytest.

---

## File Map

- Create `app/agent_tools.py`: tool registry, tool specs, structured execution for astrology, bazi, tarot, liuyao, synastry, oracle, and hybrid transit.
- Modify `app/agent.py`: call tool execution after chat context is built, attach final tool calls to assistant message metadata, keep preliminary user metadata route-only.
- Modify `tests/test_agent_api.py`: assert real chart-backed tool outputs and placeholder provider states.
- Modify `docs/app-api.md` and `docs/frontend-api-contract.md`: document `output_payload`, `error`, and provider placeholder states.
- Modify `docs/codebase-guide.md`: note `app/agent_tools.py` ownership.

## Task 1: Tool Registry and Context Execution

**Files:**
- Create: `app/agent_tools.py`
- Modify: `app/agent.py`
- Test: `tests/test_agent_api.py`

- [ ] **Step 1: Write failing tests**

```python
def test_agent_bazi_tool_uses_saved_chart_snapshot():
    user = create_agent_user()
    client.put(
        f"/api/app/users/{user['id']}/birth-profile",
        headers=APP_HEADERS,
        json={
            "chart_system": "bazi",
            "birth_date": "1989-09-29",
            "birth_time": "16:00",
            "birth_city": "兰州",
            "birth_timezone": "Asia/Shanghai",
            "bazi_profile": {
                "year_pillar": "己巳",
                "month_pillar": "癸酉",
                "day_pillar": "乙丑",
                "hour_pillar": "甲申",
                "day_master": "乙木"
            }
        },
    )
    agent_session = create_agent_session(user["id"], entry_type="free_question")
    response = client.post(
        f"/api/app/agent/sessions/{agent_session['id']}/reply",
        headers=APP_HEADERS,
        json={"content": "只用八字看我今年事业", "simulate_model_response": "先稳住节奏。"},
    )
    assert response.status_code == 200
    call = response.json()["tool_calls"][0]
    assert call["tool_name"] == "bazi_birth_chart"
    assert call["data_source"] == "user_chart_snapshot"
    assert call["output_payload"]["chart_snapshot"]["day_master"] == "乙木"
```

- [ ] **Step 2: Run red test**

Run: `.venv/bin/python -m pytest tests/test_agent_api.py::test_agent_bazi_tool_uses_saved_chart_snapshot -q`

Expected: FAIL because current tool call does not expose `output_payload.chart_snapshot`.

- [ ] **Step 3: Implement `app/agent_tools.py` and wire `app/agent.py`**

Each tool call must include:

```json
{
  "tool_name": "bazi_birth_chart",
  "system": "bazi",
  "input_payload": {},
  "output_payload": {},
  "status": "ok",
  "error": "",
  "data_source": "user_chart_snapshot"
}
```

- [ ] **Step 4: Verify green**

Run: `.venv/bin/python -m pytest tests/test_agent_api.py -q`

Expected: PASS.

## Task 2: Placeholder Provider States

**Files:**
- Modify: `app/agent_tools.py`
- Test: `tests/test_agent_api.py`

- [ ] **Step 1: Write failing tests for tarot and synastry**

```python
def test_agent_tarot_tool_returns_provider_placeholder_state():
    ...
    assert call["tool_name"] == "tarot_reading"
    assert call["output_payload"]["protocol_status"] == "awaiting_provider"


def test_agent_synastry_tool_requires_relation_profile():
    ...
    assert call["tool_name"] == "relationship_synastry"
    assert call["status"] == "needs_input"
    assert call["error"] == "relation_profile_required"
```

- [ ] **Step 2: Run red tests**

Expected: FAIL until placeholder status and relation-profile validation exist.

- [ ] **Step 3: Implement placeholder and needs-input branches**

Do not fake real tarot cards or synastry results. Return a stable provider boundary that frontends and future providers can rely on.

- [ ] **Step 4: Verify green**

Run: `.venv/bin/python -m pytest tests/test_agent_api.py -q`

Expected: PASS.

## Task 3: Documentation and Full Verification

**Files:**
- Modify: `docs/app-api.md`
- Modify: `docs/frontend-api-contract.md`
- Modify: `docs/codebase-guide.md`

- [ ] **Step 1: Document `tool_calls.output_payload`**
- [ ] **Step 2: Document `awaiting_provider` and `needs_input` states**
- [ ] **Step 3: Run full tests**

Run: `.venv/bin/python -m pytest -q`

Expected: all tests pass.

## Self-Review

- Spec coverage: Phase B covers tool registry, structured tool output, chart-backed astrology/bazi tools, and placeholder boundaries for tarot, liuyao, synastry, and oracle.
- Placeholder scan: provider placeholders are explicit product states, not code placeholders; no implementation gaps are hidden behind vague wording.
- Type consistency: `tool_name`, `system`, `input_payload`, `output_payload`, `status`, `error`, `data_source`, `needs_birth_info`, and `needs_relation_profile` remain stable for frontend integration.
