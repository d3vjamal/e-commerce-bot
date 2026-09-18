# commerce-bot — Project Overview

## 1. Purpose

A multi-agent conversational assistant for an e-commerce storefront. It accepts
a chat message plus session context, uses Amazon Bedrock models (via AWS Strands
Agents) to understand and drive the conversation, and calls the storefront's
Express backend through deterministic Python REST tools.

It is designed to be embedded in the customer app / website so a shopper can do
in natural language what they'd otherwise do by tapping around: discover
products, manage a cart, check out, track and cancel orders, and manage their
account — plus answer store-policy questions.

This repo is the **agent brain only**. The catalogue, cart, orders, payments,
and users live in a separate backend.

## 2. Architecture

```
Client app / website
        │  POST /invocations  { input: { prompt, details } }
        ▼
FastAPI (main.py)
        ▼
OrchestratorAgent  ── SOP-driven; the LLM owns routing
  ├─ IntentRouter        classify + store intent, gate on auth
  ├─ AuthAgent           adopt host JWT, or interactive sign-in
  ├─ BrowseAgent         products / categories / shops / offers   (public)
  ├─ CartAgent           view / add / update / remove cart        (auth)
  ├─ CheckoutAgent       address → delivery → coupon → pay → order (auth)
  ├─ OrderAgent          list / track / cancel orders             (auth)
  ├─ AccountAgent        addresses / wishlists / profile          (auth)
  └─ Support             answer from sops/faq.md
        ▼
tools/ecommerce_tools.py  (ecom_* @tool wrappers)
        ▼
services/ecommerce_service.py  (REST client: retry, bearer auth, JSON)
        ▼
Express e-commerce API
```

Each specialist owns an isolated Strands `Agent`, its own conversation history +
summarising manager, and an SOP under `sops/chat/`. Python tool handlers are
thin: run a sub-agent for one turn, persist state, enforce the auth gate.

## 3. Components

| Path | Role |
|---|---|
| `main.py` | FastAPI: `POST /invocations`, `GET /ping` |
| `agents/orchestrator_agent.py` | intent routing, auth gate, specialist dispatch, state reset |
| `agents/base.py` | `SpecialistAgent` base (run/reset/reply_text) |
| `agents/{auth,browse,cart,checkout,order,account}_agent.py` | specialists |
| `tools/ecommerce_tools.py` | ~100 `ecom_*` tools + per-agent selector bundles |
| `services/ecommerce_service.py` | the one REST client |
| `sops/chat/*.sop.md` | system prompts | 
| `sops/faq.md` | store policies the assistant answers support questions from |
| `models/session_context.py` | parses `input.details` |
| `configs/settings.py` | env-driven config |
| `scripts/chat.py` | local REPL |

## 4. Conversation & state

One dict under `agent.state["data"]`: `sessionContext`, `turn_count`, `intent`,
`pending_intents`, `active_agent`, `auth_state`, and one `*_state` per
specialist. Transactional specialists (checkout, order-cancel) signal
termination by calling `commerce_complete_task` / `commerce_fail_task`, which
set `status` = `COMPLETE`/`FAILED`; the orchestrator then clears the flow keys
(keeping `sessionContext`, `auth_state`, `turn_count`). See
`docs/03-orchestrator-agent.md`.

## 5. Auth

- Preferred: the host app puts the user's backend JWT in
  `input.details.authToken`; the orchestrator writes `auth_state` and never runs
  a login.
- Fallback: `AuthAgent` collects credentials and calls `ecom_login`.
- Public browsing needs neither.

## 6. Tech stack

Python ≥ 3.13.7 · `uv` · AWS Strands Agents · Amazon Bedrock (`BedrockModel`) ·
FastAPI + Uvicorn · `requests` + Tenacity · Pydantic v2 · Docker ARM64 → ECR
`agentcore-commerce-bot` → Bedrock AgentCore runtime (`deploy_agent.py`,
`buildspec.yml`).

## 7. Status & next steps

**Done (Phase A):** rename + strip of the previous hotel implementation;
`EcommerceService`; the full `ecom_*` tool library; orchestrator + 6 customer
specialists + SOPs; FAQ support; host-token adoption; wiring/tool/REST tests.

**Open items:**
1. Confirm the backend `Authorization` header scheme; then a live end-to-end run
   via `scripts/chat.py` (browse → login → cart → checkout → track → cancel).
2. Tighten payload schemas for the high-traffic tools against the real
   controllers.
3. Session isolation — replace the process-wide singleton with a
   session-keyed store for multi-session serving.
4. **Phase B:** admin agents (catalogue, order ops, promotions, insights),
   role-gated in the orchestrator SOP, `ecom_login_admin` path.
5. Optional: re-add a VOICE channel; long-term memory via `AGENTCORE_MEMORY_ID`.
