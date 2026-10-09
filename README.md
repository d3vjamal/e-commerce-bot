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
  ├─ AuthAgent        fallback sign-in (normally the host app's JWT is adopted)
  ├─ BrowseAgent      products, categories, shops, offers   (public)
  ├─ CartAgent        cart + checkout (address → pay → order) (auth)
  ├─ OrderAgent       list / track / cancel orders           (auth)
  ├─ AccountAgent     addresses, wishlists, profile          (auth)
  └─ SupportAgent     store policies / FAQ                   (public)
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

`authToken` is the shopper's backend JWT from the host app (there is no sign-in
screen in the bot). Send it on **every** request: the bot adopts a changed token
each turn, so a refreshed JWT replaces an expired one. An expired/invalid token
makes the bot ask for a fresh one. Send `userId` too — address lookups need it.

## Deploy (Docker → ECR → AgentCore)

```bash
export AGENTCORE_ROLE_ARN=<arn from infra/agentcore-role.yaml>
uv run deploy_docker.py --dry-run   # shows image + env keys that will be sent
uv run deploy_docker.py             # build ARM64 image, push to ECR, create/update runtime
```

Config comes from `.env` (or `ENV_FILE=.env.prod`); only the allow-listed
non-secret keys in `deploy_docker.py` are sent as runtime env vars, and `.env`
is never copied into the image. Each run uses a unique image tag so the runtime
always rolls out. CI/CD alternative: `infra/pipeline.yaml`. Code-only (no Docker):
`deploy_code.py`.

## Tests

```bash
uv run pytest
```

Tests cover the order service, response envelope, support tools, and the account
email gate / address validation. Agent *behaviour* is
validated by conversation, not unit tests (LLM output is non-deterministic).

## Docs

New here? Start with **`docs/00-start-here.md`** (architecture and design
explained, one request traced end to end, debugging cheat-sheet). Component
detail is in `docs/01`–`09`; `docs/09-ecommerce-tools.md` has the full tool
inventory and the backend auth contract.
