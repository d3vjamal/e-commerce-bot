# 05 — Services

## `services/ecommerce_service.py` — `EcommerceService`

The single client for the Express backend. One method does the work:

```python
request(method, path, *, params=None, payload=None, token=None,
        headers=None, timeout=None) -> Any
```

plus `get / post / put / patch / delete` shortcuts.

- **Base URL** — `settings.ecommerce_api_base_url` (`ECOMMERCE_API_BASE_URL`).
  Missing → `ValueError`.
- **Auth headers** — when `token` is passed it is sent twice:
  `Authorization: {ECOMMERCE_AUTH_SCHEME} {token}` (default `Bearer`; `""` for a
  bare token) **and** `{ECOMMERCE_TOKEN_HEADER}: {token}` (default `token`, the
  header the web app uses; set empty to disable).
- **Retry** — `@retry_api_call` (`utils/retry.py`): 3 attempts with exponential
  backoff on connection errors and HTTP 5xx. 4xx is not retried.
- **Errors** — `@handle_errors` logs and re-raises; the tool layer
  (`_EcomToolBase._call`) catches and returns `{"error": ..., "message": ...}`
  so the LLM can react instead of the turn crashing.
- **Return** — decoded JSON, or `{"statusCode": ...}` / `{"raw": ...}` for empty
  / non-JSON bodies.
- `Authorization` and `token` headers are masked in debug logs.
- A 401 becomes `error="token_expired"` — in `ResponseBuilder` (order service)
  and in `_EcomToolBase._call` (all other tools).

## `configs/settings.py` — `Settings`

Env-driven singleton, validated at import (`REGION`, `ORCHESTRATOR_MODEL_ID`
required). Key vars:

| Var | Purpose |
|---|---|
| `REGION` | AWS region for Bedrock |
| `ORCHESTRATOR_MODEL_ID` | model for every agent by default |
| `SPECIALIST_MODEL_ID`, `AUTH_MODEL_ID` | optional per-tier overrides |
| `GUARDRAIL_ID`, `GUARDRAIL_VERSION` | optional Bedrock guardrail on the orchestrator |
| `ECOMMERCE_API_BASE_URL` | Express backend root |
| `ECOMMERCE_AUTH_SCHEME` | `Bearer` (default) / `""` / custom |
| `ECOMMERCE_TOKEN_HEADER` | raw-JWT header name (default `token`; empty disables) |
| `ECOMMERCE_API_TIMEOUT` | per-request seconds (default 30) |
| `BRAND_NAME` | substituted into SOPs as `{{BRAND_NAME}}` |
| `AGENTCORE_MEMORY_ID` | reserved for long-term memory (unused today) |
