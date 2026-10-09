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
  - `authToken` — the shopper's JWT. The orchestrator writes `auth_state` from it
    and **re-adopts it every turn if it changed**, so send the current token on
    every request. AuthAgent is never invoked when it is supplied.
  - `userId` — needed for address lookups (`GET /user-address?userId=`).
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

## Session model

`main.py` keeps one `OrchestratorAgent` per
`x-amzn-bedrock-agentcore-runtime-session-id` in an in-process dict, so a
conversation continues across turns. A request with no session header gets a
fresh, unstored orchestrator each turn (no leakage, no continuity). State is
lost on restart/another instance — see the risks in `06-hld.md`.
