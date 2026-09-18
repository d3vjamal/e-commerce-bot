# 02 — API server

`main.py` is a FastAPI app with two routes.

## `POST /invocations`

Request (`models/agent_invocation_model.py`):

```json
{
  "input": {
    "prompt": "add the second one to my cart",
    "details": {
      "channel": "CHAT",
      "role": "customer",
      "userId": "u_123",
      "authToken": "<backend JWT>"
    }
  }
}
```

- `prompt` (required) — the user message. Missing/empty → `400`.
- `details` (optional) — parsed into `SessionContext`
  (`models/session_context.py`). Unknown keys are tolerated.
  - `authToken` — when present, the orchestrator writes `auth_state` directly and
    the AuthAgent is never invoked (silent adoption).
  - `role` — `customer` (default), `admin`, `delivery`. Admin routing is Phase B.

Response:

```json
{
  "output": {
    "message": "…assistant reply…",
    "timestamp": "2026-…Z",
    "sessionId": "<x-amzn-bedrock-agentcore-runtime-session-id header>",
    "sessionData": { "...": "full agent.state['data']" },
    "timeTaken": "1.234 Secs"
  }
}
```

## `GET /ping`

`{"status": "healthy"}` — health check.

## Session model & known limitation

One process-wide `OrchestratorAgent` instance is created at startup. On the
Bedrock AgentCore runtime that is one logical conversation per runtime session,
which is fine. **A multi-session server must key an orchestrator/state store by
`sessionId`** instead — the current singleton shares conversation history and
`agent.state` across concurrent callers. This is the top hardening item.
