# 04 — Specialist agents

All specialists extend `agents/base.py::SpecialistAgent`: an isolated Strands
`Agent`, a `SummarizingConversationManager`, an SOP from `sops/chat/`, and a
curated tool bundle from `tools/ecommerce_tools.py`. Contract:

```python
run(user_input: str, state: {"data": {...}}) -> (response, {"data": {...}})
reset() -> None
reply_text(response) -> str
```

The orchestrator passes the shared `data` dict in and persists whatever comes
back, so a specialist reads `auth_state.token` (via its tools) without ever
being handed the token directly.

| Agent | File | SOP | Tool bundle | Auth |
|---|---|---|---|---|
| AuthAgent | `auth_agent.py` | `chat/auth.sop.md` | `auth_tools` | — |
| BrowseAgent | `browse_agent.py` | `chat/browse.sop.md` | `browse_tools` | no |
| CartAgent | `cart_agent.py` | `chat/cart.sop.md` | `cart_tools` | yes |
| CheckoutAgent | `checkout_agent.py` | `chat/checkout.sop.md` | `checkout_tools` | yes |
| OrderAgent | `order_agent.py` | `chat/order.sop.md` | `order_tools` | yes |
| AccountAgent | `account_agent.py` | `chat/account.sop.md` | `account_tools` | yes |

## AuthAgent

Collects email + password (or social provider details) and calls `ecom_login` /
`ecom_login_social`, which store `auth_state = {token, user,
verification_status: "PASS"}`. Also handles `ecom_register_user` and
`ecom_forgot_password`. When the host app supplied `authToken` the orchestrator
adopts it and this agent is skipped entirely.

## BrowseAgent

Public. Turns vague asks into concrete `ecom_search_products` filters; drills
into one product with `ecom_get_product_details` / `_options`; uses
`ecom_search_products_by_address` when the user mentions a location. Never
invents catalogue data.

## CartAgent

Resolves the user's phrasing to a `productId` (+ `optionId`), mutates the cart,
and reads it back after every change. Hands off to checkout on "buy now".

## CheckoutAgent

Strict ordered flow (see `chat/checkout.sop.md`): review cart → address →
delivery charge → optional coupon → payment method → **explicit total
confirmation** → `ecom_place_order` → Razorpay create/verify/capture for online
payments → `commerce_complete_task` with the `order_id`. Never places the order
before confirmation.

## OrderAgent

`ListOrders` / `TrackOrder` from `ecom_get_my_orders` + `ecom_get_order_details`.
`CancelOrder` = identify order → reason → confirm → `ecom_cancel_order_by_customer`
→ `commerce_complete_task` / `commerce_fail_task`.

## AccountAgent

Address CRUD, wishlist add/remove/list, and profile fields
(`ecom_get_user_details` / `ecom_update_user`). Confirms deletes; reads state
before and after changes. Email/password changes are out of scope.
