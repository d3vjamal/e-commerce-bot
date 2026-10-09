# 03 — Orchestrator agent

`agents/orchestrator_agent.py`. SOP: `sops/chat/orchestrator.sop.md`.

## Responsibilities

- Adopt/refresh the host JWT into `auth_state` at the start of every turn.

- Classify intent(s) via the `IntentRouter` tool.
- Enforce the auth gate for account-scoped intents.
- Run exactly one specialist per turn and relay its result.
- Reset per-flow state when a task completes or the user switches tasks.

All *decisions* are the LLM's, guided by the SOP. The Python handlers are
mechanical.

## Tools exposed to the orchestrator LLM

| Tool | Purpose |
|---|---|
| `IntentRouter(intent: list[str])` | sanitise + store intents, bump `turn_count`, return routing signal |
| `Auth(user_input)` | reach `auth_state.verification_status == "PASS"` |
| `BrowseCatalogue(user_input)` | run BrowseAgent one turn |
| `ManageCart(user_input)` | run CartAgent one turn — cart and checkout (auth) |
| `ManageOrders(user_input)` | run OrderAgent one turn (auth) |
| `ManageAccount(user_input)` | run AccountAgent one turn (auth) |
| `Support(user_input)` | return `sops/faq.md` text for the LLM to answer from |
| `Fallback(user_input)` | out-of-scope reply |

### `IntentRouter` response

```json
{
  "validated_intents": ["CART"],
  "turn_count": 3,
  "active_agent": "CART" | null,
  "auth_status": "PASS" | null,
  "auth_required": true,
  "pending_intents": ["CART"],
  "role": "customer"
}
```

Intents: `BROWSE`, `PRODUCT_DETAIL`, `CART`, `CHECKOUT`, `ORDER_TRACK`,
`ORDER_CANCEL`, `ACCOUNT`, `SUPPORT`, `UNKNOWN`. `AUTH_INTENTS` (need sign-in) =
`CART`, `CHECKOUT`, `ORDER_TRACK`, `ORDER_CANCEL`, `ACCOUNT`.

### Specialist result

```json
{ "status": "IN_PROGRESS", "response": "…" }
{ "status": "COMPLETE", "message": "…", "order_id": "…" }
{ "status": "FAILED", "message": "…" }
{ "status": "AUTH_REQUIRED", "message": "…" }
```

`COMPLETE` / `FAILED` come from a specialist calling `commerce_complete_task` /
`commerce_fail_task`; the orchestrator then calls `_reset_flow_state`.

## Session state — `agent.state["data"]`

```
sessionContext   { channel, role, userId, authToken? }   from input.details
turn_count       int
intent           last classified list
pending_intents  intents still to handle (ordered)
active_agent     "AUTH" | "BROWSE" | "CART" | "ORDER" | "ACCOUNT" | null
auth_state       { token, user, verification_status: "PASS"|"PENDING"|"FAILED", source?,
                   email_verified?, email_attempts? }   # token refreshed every turn from authToken
browse_state     { flow_started, ... }
cart_state       { flow_started, ... }
order_state      { flow_started, ... }
account_state    { flow_started, ... }
status           "COMPLETE"|"FAILED" — set by a transactional specialist, consumed then cleared
task_summary     user-facing one-liner for COMPLETE/FAILED
order_id         set on a completed checkout / cancellation
```

`_reset_flow_state` clears everything except `sessionContext`, `auth_state`, and
`turn_count`, and calls `reset()` on every specialist.
