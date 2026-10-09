# 01 — Overview

> New to the project? Read `00-start-here.md` first.

`commerce-bot` is a multi-agent conversational assistant for an e-commerce
storefront. It is the agent brain only — the catalogue, cart, orders, payments,
and users live in a separate Express + TypeScript backend that this service
calls over REST.

## What it does

| Capability | Agent | Sign-in |
|---|---|---|
| Find / compare products, categories, shops, offers | BrowseAgent | no |
| View & modify the cart | CartAgent | yes |
| Checkout: address → delivery → coupon → payment → place order | CartAgent | yes |
| List / track / cancel orders | OrderAgent | yes |
| Addresses, wishlists, profile | AccountAgent | yes |
| Sign in / register / password reset (fallback; host JWT is normally used) | AuthAgent | — |
| Store-policy questions (returns, delivery, payments) | Orchestrator + `sops/faq.md` | no |

## Design principles (inherited from the original architecture)

1. **The LLM owns routing.** The orchestrator SOP describes intents and flow;
   Python `@tool` handlers only run a sub-agent, persist state, and enforce the
   auth gate. No routing branches in Python.
2. **Specialists are isolated.** Each owns its own `Agent`, conversation
   history, summarising manager, and SOP. They never see each other's history.
3. **Tools are thin.** One `ecom_*` tool per backend endpoint; deterministic
   REST calls, no business logic.
4. **State is one dict.** Everything lives under `agent.state["data"]` — see
   `docs/03-orchestrator-agent.md`.

## Stack

| Area | Choice |
|---|---|
| Language | Python ≥ 3.13.7, `uv` |
| Agent framework | AWS Strands Agents |
| LLM | Amazon Bedrock via `BedrockModel` |
| API | FastAPI + Uvicorn |
| Backend client | `requests` + Tenacity retry (`services/ecommerce_service.py`) |
| Deploy | Docker ARM64 → ECR `agentcore-commerce-bot` → Bedrock AgentCore runtime |

## Repository map

```
agents/     orchestrator + specialist agents (base.py = shared specialist class)
tools/      ecommerce_tools.py — the ecom_* tool library + per-agent selectors
services/   ecommerce_service.py — the REST client
sops/       chat/*.sop.md system prompts + faq.md (store policies)
models/     invocation + session-context pydantic models
configs/    settings.py — env-driven config
scripts/    chat.py — local REPL
tests/      wiring / tool-selection / REST-client tests
main.py     FastAPI entry point
```
