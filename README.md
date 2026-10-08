# commerce-bot

A multi-agent e-commerce assistant built with **AWS Strands Agents**, **Amazon
Bedrock**, and **FastAPI**. It embeds in a storefront app / website and lets a
shopper browse the catalogue, manage their cart, check out, track and cancel
orders, manage their account, and ask store-policy questions — everything a user
does in the app, driven by natural language.

The catalogue, cart, orders, etc. live in a separate **Express backend**; this
repo is the agent brain and calls that backend over REST.

## Architecture

```
POST /invocations (FastAPI, main.py)
        │
        ▼
OrchestratorAgent ── SOP-driven, LLM owns routing
  ├─ AuthAgent        sign-in (or adopt the host app's JWT)
  ├─ BrowseAgent      products, categories, shops, offers   (public)
  ├─ CartAgent        cart + checkout (address → pay → order) (auth)
  ├─ OrderAgent       list / track / cancel orders           (auth)
  └─ AccountAgent     addresses, wishlists, profile          (auth)
        │
        ▼
tools/ecommerce_tools.py  →  services/ecommerce_service.py  →  Express API
```

Each specialist owns an isolated Strands `Agent` + summarising conversation
manager and an SOP under `sops/chat/`. Tools are thin REST wrappers
(`ecom_*`); the LLM decides which to call.

## Setup

1. Copy `.env` and fill in real values:
   ```bash
   cp .env .env.local     # then edit
   ```
   Required: `REGION`, `ORCHESTRATOR_MODEL_ID`, `ECOMMERCE_API_BASE_URL`.
   See `.env` for the full list.

2. Install dependencies:
   ```bash
   uv sync --group dev
   ```

3. Run the server:
   ```bash
   uv run uvicorn main:app --host 0.0.0.0 --port 8080 --reload
   ```

4. Or chat locally:
   ```bash
   uv run python scripts/chat.py
   AUTH_TOKEN=<jwt> uv run python scripts/chat.py   # pre-authenticated
   ```

## Request shape

```json
{
  "input": {
    "prompt": "show me wireless earbuds under 3000",
    "details": { "channel": "CHAT", "role": "customer", "userId": "u_123", "authToken": "<jwt>" }
  }
}
```

`authToken` is optional — when present the assistant skips the login flow.

## Tests

```bash
uv run pytest
```

Tests cover wiring, tool selection, and the REST client. Agent *behaviour* is
validated by conversation, not unit tests (LLM output is non-deterministic).

## Docs

See `docs/` for component-level detail and `docs/09-ecommerce-tools.md` for the
full tool inventory and the backend auth contract.
