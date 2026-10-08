# 09 — E-commerce tools

`tools/ecommerce_tools.py` wraps every route of the Express backend as a Strands
`@tool` named `ecom_<action>` (plus `commerce_*` flow-control tools). Grouped by
controller into `_EcomToolBase` subclasses; specialist agents take curated
subsets via the selector helpers.

## Auth contract

- Public routes are called with no token.
- Authenticated routes read the token from
  `agent.state["data"]["auth_state"]["token"]` and send
  `Authorization: {ECOMMERCE_AUTH_SCHEME} {token}` (default `Bearer`).
- If no token is present, the tool returns
  `{"error": "not_authenticated", "message": ...}` — the SOP tells the agent to
  route back through sign-in.
- `ecom_login` / `ecom_login_social` / `ecom_login_admin` parse the token out of
  the response (`token`, `accessToken`, `tokens.*`, `data.*`, …) and set
  `auth_state.verification_status = "PASS"`.

> **TODO before go-live:** confirm the backend's header scheme
> (`../policies/Authorizer`). If it expects a bare token set
> `ECOMMERCE_AUTH_SCHEME=""`; if `x-access-token`, adjust `_build_headers`.

## Request/response shapes

Tools pass free-form dicts (`payload` / `updates` / `filters`) because the
controller schemas are not modelled here. Tighten the high-traffic ones against
the real controllers using live responses from `scripts/chat.py`:
`ecom_search_products`, `ecom_add_to_cart`, `ecom_place_order`,
`ecom_validate_coupon`, `ecom_get_delivery_charges`.

## Selector helpers (per-agent bundles)

| Helper | Used by | Tools |
|---|---|---|
| `auth_tools` | AuthAgent | login, login_social, register_user, forgot_password, verify_email, resend_verification |
| `browse_tools` | BrowseAgent | product/category/shop/banner/home-feed **reads** only |
| `cart_tools` | CartAgent | cart get/add/update/remove, product detail/options, address reads + add, delivery_charges, validate_coupon, place_order, razorpay ×3, `commerce_complete_task/_fail_task` |
| `order_tools` | OrderAgent | get_my_orders, get_order_details, cancel_order_by_customer, `commerce_*` |
| `account_tools` | AccountAgent | address CRUD, wishlist, get_user_details, update_user |

`build_ecommerce_toolset(logger_config)` returns every tool (used by tests /
introspection).

## Full inventory

### Users & auth — `UserAuthTools`
`ecom_login`, `ecom_login_admin`, `ecom_login_social`, `ecom_logout`,
`ecom_register_user`, `ecom_add_user`, `ecom_update_user`,
`ecom_update_user_return_tokens`, `ecom_delete_user`, `ecom_search_users`,
`ecom_get_user_details`, `ecom_forgot_password`, `ecom_reset_password`,
`ecom_verify_email`, `ecom_resend_verification`

### Shops — `ShopTools`
`ecom_register_shop`, `ecom_search_shops`, `ecom_update_shop`

### Addresses — `AddressTools`
`ecom_add_address`, `ecom_update_address`, `ecom_delete_address`,
`ecom_get_addresses`, `ecom_get_default_address`, `ecom_get_delivery_charges`

### Uploads — `UploadTools`
`ecom_get_upload_keys`, `ecom_remove_files`

### Categories — `CategoryTools`
`ecom_add_category`, `ecom_update_category`, `ecom_delete_category`,
`ecom_search_categories`, `ecom_search_shop_categories`, `ecom_add_sub_category`,
`ecom_update_sub_category`, `ecom_delete_sub_category`,
`ecom_search_sub_categories`, `ecom_search_categories_with_sub`,
`ecom_get_sub_categories_by_category`

### Products, options & cart — `ProductTools`
`ecom_add_product`, `ecom_update_product`, `ecom_delete_product`,
`ecom_search_products`, `ecom_search_products_by_address`,
`ecom_get_shop_products`, `ecom_get_product_details`,
`ecom_add_product_options`, `ecom_get_product_options`,
`ecom_update_product_options`, `ecom_delete_product_options`,
`ecom_add_to_cart`, `ecom_get_my_cart`, `ecom_update_cart`,
`ecom_remove_from_cart`

### Banners — `BannerTools`
`ecom_add_banner`, `ecom_update_banner`, `ecom_delete_banner`,
`ecom_search_banners`, `ecom_get_banner_positions`

### Location groups — `LocationGroupTools`
`ecom_add_location_group`, `ecom_update_location_group`,
`ecom_delete_location_group`, `ecom_search_location_groups`

### Payments — `PaymentTools`
`ecom_add_payment`, `ecom_update_payment`, `ecom_delete_payment`,
`ecom_search_payments`

### Wishlists — `WishlistTools`
`ecom_add_wishlist`, `ecom_update_wishlist`, `ecom_delete_wishlist`,
`ecom_search_wishlists`, `ecom_get_my_wishlist`, `ecom_add_to_wishlist`,
`ecom_remove_from_wishlist`

### Orders — `OrderTools`
`ecom_add_order`, `ecom_place_order`, `ecom_update_order`, `ecom_delete_order`,
`ecom_search_orders`, `ecom_get_my_orders`, `ecom_search_deliveryboy_orders`,
`ecom_get_order_details`, `ecom_cancel_order_by_customer`,
`ecom_reject_cancel_order_by_admin`

### Home feed — `HomeFeedTools`
`ecom_add_home_feed`, `ecom_update_home_feed`, `ecom_delete_home_feed`,
`ecom_search_home_feeds`

### Dashboard — `DashboardTools`
`ecom_get_dashboard_data`, `ecom_get_orders_dashboard_data`

### Razorpay — `RazorpayTools`
`ecom_create_razorpay_order`, `ecom_verify_razorpay_payment`,
`ecom_capture_razorpay_payment`

### Coupons — `CouponTools`
`ecom_add_coupon`, `ecom_update_coupon`, `ecom_delete_coupon`,
`ecom_search_coupons`, `ecom_validate_coupon`

### Flow control — `FlowControlTools`
`commerce_complete_task`, `commerce_fail_task`

## Phase B (admin)

The write-heavy groups (`ProductTools`, `CategoryTools`, `BannerTools`,
`CouponTools`, `LocationGroupTools`, `PaymentTools`, `DashboardTools`,
`OrderTools` admin methods, `ShopTools`, `UserAuthTools` admin methods) are
ready but not yet wired to agents. Phase B adds `agents/admin/*`, role-gated
intents, and the `ecom_login_admin` path.
