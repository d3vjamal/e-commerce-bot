"""
Strands tools wrapping the e-commerce Express backend.

Every route in the API is exposed here as an ``@tool`` method, grouped by
controller. Tools are named ``ecom_<action>`` so they are easy to spot in
traces and prompts.

Auth model
----------
Most routes sit behind ``IsAuthenticated``. The agent reaches an authenticated
state in one of two ways:

- the host app passes the user's existing JWT in the invocation payload
  (``input.details.authToken``) and the AuthAgent adopts it, or
- the AuthAgent runs an interactive login (``ecom_login`` /
  ``ecom_login_social``).

Either way the token lands in agent state under
``state["data"]["auth_state"]`` as
``{"token", "user", "verification_status": "PASS"}`` and is attached as the
``Authorization`` header on every subsequent authenticated call. Endpoints
that the Express router leaves open (product/category/banner search, shop
search, …) are called without a token.

Usage
-----
    from utils.logger_config import LoggerConfig
    from tools.ecommerce_tools import build_ecommerce_toolset

    tools = build_ecommerce_toolset(LoggerConfig())
    agent = Agent(model=..., tools=tools, ...)

Request/response bodies are passed through as free-form dicts because the
controller schemas are not modelled here — tighten the signatures once the
exact payload shapes are known.
"""

import re
from typing import Any, Dict, List, Optional

from strands import ToolContext, tool

from services.ecommerce_service import EcommerceService
from utils.logger import Logger


# ─────────────────────────────────────────────────────────────────────────────
# Base
# ─────────────────────────────────────────────────────────────────────────────


class _EcomToolBase:
    """Shared helpers for every e-commerce tool group."""

    AUTH_STATE_KEY = "auth_state"

    def __init__(self, logger_config):
        self.logger = Logger(__name__, logger_config)
        self.api = EcommerceService(logger_config)

    # -- state helpers ---------------------------------------------------

    @staticmethod
    def _data(tool_context: ToolContext) -> Dict[str, Any]:
        return tool_context.agent.state.get("data") or {}

    def _token(self, tool_context: ToolContext) -> Optional[str]:
        return self._data(tool_context).get(self.AUTH_STATE_KEY, {}).get("token")

    @staticmethod
    def _extract_token(body: Any) -> Optional[str]:
        """Best-effort pull of a JWT out of an auth response of unknown shape."""
        if not isinstance(body, dict):
            return None
        for key in (
            "token",
            "accessToken",
            "access_token",
            "jwt",
            "authToken",
            "idToken",
        ):
            value = body.get(key)
            if isinstance(value, str) and value:
                return value
        for container in ("tokens", "data", "result", "user", "auth", "payload"):
            nested = body.get(container)
            found = _EcomToolBase._extract_token(nested)
            if found:
                return found
        return None

    # -- request helper ------------------------------------------------------

    def _call(
        self,
        tool_context: Optional[ToolContext],
        method: str,
        path: str,
        *,
        auth: bool = True,
        params: Optional[Dict[str, Any]] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Any:
        token = None
        if auth:
            if tool_context is None:
                return {
                    "error": "not_authenticated",
                    "message": "No tool context available to read the auth token.",
                }
            token = self._token(tool_context)
            if not token:
                return {
                    "error": "not_authenticated",
                    "message": (
                        "This action needs a signed-in user. Ask the user for "
                        "credentials and call ecom_login first."
                    ),
                }
        try:
            return self.api.request(
                method, path, params=params, payload=payload, token=token
            )
        except Exception as exc:  # noqa: BLE001 - surface error to the LLM
            self.logger.exception(f"[ecom] {method} {path} failed")
            return {"error": "request_failed", "message": str(exc)}

    # -- tool collection ---------------------------------------------------

    def tools(self) -> List[Any]:
        """Return every ``@tool``-decorated method on this group."""
        collected = []
        for name in dir(self):
            if name.startswith("_"):
                continue
            attr = getattr(self, name, None)
            if attr is not None and hasattr(attr, "tool_spec"):
                collected.append(attr)
        return collected


# ─────────────────────────────────────────────────────────────────────────────
# Users & authentication
# ─────────────────────────────────────────────────────────────────────────────


class UserAuthTools(_EcomToolBase):
    """User accounts, login, password, and email verification."""

    @tool(context=True, name="ecom_login")
    def login(self, credentials: Dict[str, Any], tool_context: ToolContext) -> Any:
        """Authenticate a shopper and store the session token in agent state.

        POST /auth-user (public). Call this before any authenticated tool.

        Args:
            credentials: Login body expected by the API, e.g.
                {"email": "a@b.com", "password": "..."} or {"phone": "...", "otp": "..."}.
        """
        body = self._call(None, "POST", "/auth-user", auth=False, payload=credentials)
        return self._store_auth(body, tool_context)

    @tool(context=True, name="ecom_login_admin")
    def login_admin(
        self, credentials: Dict[str, Any], tool_context: ToolContext
    ) -> Any:
        """Authenticate an admin user and store the token in agent state.

        POST /auth-admin (public).

        Args:
            credentials: {"email": ..., "password": ...}.
        """
        body = self._call(None, "POST", "/auth-admin", auth=False, payload=credentials)
        return self._store_auth(body, tool_context)

    @tool(context=True, name="ecom_login_social")
    def login_social(
        self, social_payload: Dict[str, Any], tool_context: ToolContext
    ) -> Any:
        """Authenticate via a social provider token and store the session token.

        POST /auth-user-social (public).

        Args:
            social_payload: Provider payload, e.g. {"provider": "google", "idToken": "..."}.
        """
        body = self._call(
            None, "POST", "/auth-user-social", auth=False, payload=social_payload
        )
        return self._store_auth(body, tool_context)

    @tool(context=True, name="ecom_logout")
    def logout(self, tool_context: ToolContext) -> Any:
        """Clear the stored e-commerce session token from agent state (local only)."""
        data = self._data(tool_context)
        data.pop(self.AUTH_STATE_KEY, None)
        tool_context.agent.state.set("data", data)
        return {"status": "logged_out"}

    @tool(name="ecom_register_user")
    def register_user(self, user: Dict[str, Any]) -> Any:
        """Register a new shopper account.

        PUT /register-user (public).

        Args:
            user: New-user body, e.g. {"name": ..., "email": ..., "password": ...}.
        """
        return self._call(None, "PUT", "/register-user", auth=False, payload=user)

    @tool(context=True, name="ecom_add_user")
    def add_user(self, user: Dict[str, Any], tool_context: ToolContext) -> Any:
        """Create a user as an authenticated admin.

        PUT /users (auth).

        Args:
            user: New-user body.
        """
        return self._call(tool_context, "PUT", "/users", payload=user)

    @tool(context=True, name="ecom_update_user")
    def update_user(
        self, user_id: str, updates: Dict[str, Any], tool_context: ToolContext
    ) -> Any:
        """Update a user's profile fields.

        PATCH /users/:userId (auth).

        Args:
            user_id: Target user id.
            updates: Partial user fields to change.
        """
        return self._call(
            tool_context, "PATCH", f"/users/{user_id}", payload=updates
        )

    #: wrong-email attempts allowed before account changes are locked
    MAX_EMAIL_ATTEMPTS = 3

    @staticmethod
    def _find_email(body: Any) -> Optional[str]:
        """Pull an email address out of a user payload of unknown nesting."""
        if not isinstance(body, dict):
            return None
        value = body.get("email")
        if isinstance(value, str) and value:
            return value
        for key in ("data", "user", "result", "profile"):
            found = UserAuthTools._find_email(body.get(key))
            if found:
                return found
        return None

    def _is_email_verified(self, tool_context: ToolContext) -> bool:
        return bool(
            self._data(tool_context).get(self.AUTH_STATE_KEY, {}).get("email_verified")
        )

    _EMAIL_NOT_VERIFIED = {
        "error": "email_not_verified",
        "message": (
            "Ask the user for the email address linked to their account and "
            "call ecom_verify_account_email before making this change."
        ),
    }

    @tool(context=True, name="ecom_verify_account_email")
    def verify_account_email(self, email: str, tool_context: ToolContext) -> Any:
        """Check the email address the user typed against the email linked to
        the signed-in account. Required once before profile or address changes.

        Args:
            email: The linked email address, exactly as the user typed it.
        """
        data = self._data(tool_context)
        auth = data.get(self.AUTH_STATE_KEY) or {}
        if auth.get("email_verified"):
            return {"status": "verified"}
        if auth.get("email_attempts", 0) >= self.MAX_EMAIL_ATTEMPTS:
            return {
                "error": "too_many_attempts",
                "message": "Too many incorrect attempts. Account changes are locked for this session.",
            }
        user = auth.get("user") or {}
        linked = self._find_email(user)
        if not linked:
            user_id = user.get("_id") or user.get("id")
            if not user_id:
                return {"error": "user_unknown", "message": "Could not determine the signed-in user."}
            details = self._call(tool_context, "GET", f"/user/{user_id}")
            linked = self._find_email(details)
        if not linked:
            return {"error": "email_unavailable", "message": "Could not read the linked email for this account."}
        if (email or "").strip().lower() != linked.strip().lower():
            auth["email_attempts"] = auth.get("email_attempts", 0) + 1
            data[self.AUTH_STATE_KEY] = auth
            tool_context.agent.state.set("data", data)
            return {
                "error": "email_mismatch",
                "message": "That email does not match the account. Do not reveal the real email.",
            }
        auth["email_verified"] = True
        data[self.AUTH_STATE_KEY] = auth
        tool_context.agent.state.set("data", data)
        return {"status": "verified"}

    #: fields a shopper may never set on their own profile
    PROTECTED_PROFILE_FIELDS = frozenset(
        {
            "_id",
            "id",
            "email",
            "password",
            "role",
            "roles",
            "status",
            "isVerified",
            "isEmailVerified",
            "isActive",
            "isAdmin",
            "token",
            "tokens",
        }
    )

    @tool(context=True, name="ecom_update_my_profile")
    def update_my_profile(
        self, updates: Dict[str, Any], tool_context: ToolContext
    ) -> Any:
        """Update the signed-in user's own profile (name, mobile / contact
        number, etc.). Email, password, role and verification fields cannot be
        changed here. The user id is taken from the session.

        PATCH /users/:userId (auth).

        Args:
            updates: Partial profile fields to change, e.g. {"phone": "..."}.
        """
        if not self._is_email_verified(tool_context):
            return self._EMAIL_NOT_VERIFIED
        user = self._data(tool_context).get(self.AUTH_STATE_KEY, {}).get("user") or {}
        user_id = user.get("_id") or user.get("id")
        if not user_id:
            return {
                "error": "user_unknown",
                "message": "Could not determine the signed-in user id.",
            }
        rejected = sorted(set(updates) & self.PROTECTED_PROFILE_FIELDS)
        if rejected or not updates:
            return {
                "error": "fields_not_allowed" if rejected else "no_updates",
                "message": "Email, password, role and verification cannot be changed here.",
                "rejected": rejected,
            }
        return self._call(
            tool_context, "PATCH", f"/users/{user_id}", payload=updates
        )

    @tool(context=True, name="ecom_update_user_return_tokens")
    def update_user_return_tokens(
        self, user_id: str, updates: Dict[str, Any], tool_context: ToolContext
    ) -> Any:
        """Update a user and receive refreshed auth tokens; stores the new token.

        PATCH /users-return-tokens/:userId (auth).

        Args:
            user_id: Target user id.
            updates: Partial user fields to change.
        """
        body = self._call(
            tool_context,
            "PATCH",
            f"/users-return-tokens/{user_id}",
            payload=updates,
        )
        token = self._extract_token(body)
        if token:
            data = self._data(tool_context)
            existing = data.get(self.AUTH_STATE_KEY, {})
            data[self.AUTH_STATE_KEY] = {
                "token": token,
                "user": self._extract_user(body) or existing.get("user"),
                "verification_status": "PASS",
            }
            tool_context.agent.state.set("data", data)
        return body

    @tool(context=True, name="ecom_delete_user")
    def delete_user(self, user_id: str, tool_context: ToolContext) -> Any:
        """Delete a user account.

        DELETE /users/:userId (auth).

        Args:
            user_id: Target user id.
        """
        return self._call(tool_context, "DELETE", f"/users/{user_id}")

    @tool(context=True, name="ecom_search_users")
    def search_users(
        self, tool_context: ToolContext, filters: Optional[Dict[str, Any]] = None
    ) -> Any:
        """Search / list users.

        GET /users (auth).

        Args:
            filters: Query params, e.g. {"search": "...", "page": 1, "limit": 20}.
        """
        return self._call(tool_context, "GET", "/users", params=filters)

    @tool(context=True, name="ecom_get_user_details")
    def get_user_details(self, user_id: str, tool_context: ToolContext) -> Any:
        """Get one user's full details.

        GET /user/:userId (auth).

        Args:
            user_id: Target user id.
        """
        return self._call(tool_context, "GET", f"/user/{user_id}")

    @tool(name="ecom_forgot_password")
    def forgot_password(self, payload: Dict[str, Any]) -> Any:
        """Start the forgot-password flow (sends a reset link/OTP).

        POST /forgot-password (public).

        Args:
            payload: {"email": "..."} (or as the API expects).
        """
        return self._call(None, "POST", "/forgot-password", auth=False, payload=payload)

    @tool(name="ecom_reset_password")
    def reset_password(self, payload: Dict[str, Any]) -> Any:
        """Complete a password reset with a token/OTP and a new password.

        POST /reset-password (public).

        Args:
            payload: {"token": "...", "password": "..."} (or as the API expects).
        """
        return self._call(None, "POST", "/reset-password", auth=False, payload=payload)

    @tool(name="ecom_verify_email")
    def verify_email(self, payload: Dict[str, Any]) -> Any:
        """Verify an email address with a verification token/code.

        POST /verify-email (public).

        Args:
            payload: {"token": "..."} or {"email": "...", "code": "..."}.
        """
        return self._call(None, "POST", "/verify-email", auth=False, payload=payload)

    @tool(name="ecom_resend_verification")
    def resend_verification(self, payload: Dict[str, Any]) -> Any:
        """Resend the email-verification message.

        POST /resend-verification (public).

        Args:
            payload: {"email": "..."}.
        """
        return self._call(
            None, "POST", "/resend-verification", auth=False, payload=payload
        )

    # -- internal --------------------------------------------------------

    @staticmethod
    def _extract_user(body: Any) -> Any:
        if not isinstance(body, dict):
            return None
        for key in ("user", "data", "result", "profile"):
            value = body.get(key)
            if isinstance(value, dict) and (
                value.get("_id") or value.get("id") or value.get("email")
            ):
                return value
        if body.get("_id") or body.get("email"):
            return body
        return None

    def _store_auth(self, body: Any, tool_context: ToolContext) -> Any:
        if isinstance(body, dict) and body.get("error"):
            return body
        token = self._extract_token(body)
        if not token:
            self.logger.warning("[ecom] auth response had no recognisable token")
            return {
                "error": "no_token",
                "message": "Authentication response contained no token.",
                "response": body,
            }
        data = self._data(tool_context)
        data[self.AUTH_STATE_KEY] = {
            "token": token,
            "user": self._extract_user(body),
            "verification_status": "PASS",
        }
        tool_context.agent.state.set("data", data)
        self.logger.info("[ecom] session token stored in agent state (auth_state)")
        return {
            "status": "authenticated",
            "verification_status": "PASS",
            "user": data[self.AUTH_STATE_KEY]["user"],
        }


# ─────────────────────────────────────────────────────────────────────────────
# Shops
# ─────────────────────────────────────────────────────────────────────────────


class ShopTools(_EcomToolBase):
    """Shop registration and search."""

    @tool(context=True, name="ecom_register_shop")
    def register_shop(self, shop: Dict[str, Any], tool_context: ToolContext) -> Any:
        """Register a new shop.

        PUT /shops (auth). Same handler as PUT /shop-add.

        Args:
            shop: Shop registration body.
        """
        return self._call(tool_context, "PUT", "/shops", payload=shop)

    @tool(name="ecom_search_shops")
    def search_shops(self, filters: Optional[Dict[str, Any]] = None) -> Any:
        """Search for shops.

        POST /shops (public).

        Args:
            filters: Search body, e.g. {"search": "...", "location": {...}, "page": 1}.
        """
        return self._call(None, "POST", "/shops", auth=False, payload=filters or {})

    @tool(context=True, name="ecom_update_shop")
    def update_shop(
        self, shop_id: str, updates: Dict[str, Any], tool_context: ToolContext
    ) -> Any:
        """Update a shop.

        POST /shops/:id (auth).

        Args:
            shop_id: Target shop id.
            updates: Partial shop fields to change.
        """
        return self._call(
            tool_context, "POST", f"/shops/{shop_id}", payload=updates
        )


# ─────────────────────────────────────────────────────────────────────────────
# Addresses
# ─────────────────────────────────────────────────────────────────────────────


#: address fields the shopper can never change
_ADDRESS_LOCKED = frozenset({"_id", "id", "userId", "user", "createdAt", "updatedAt"})


_ADDRESS_REQUIRED = ("name", "phone", "pincode", "addressLine1", "city")
_ADDRESS_TYPES = ("home", "work")


def _validate_address(fields: Dict[str, Any], *, require_all: bool) -> Optional[Dict[str, Any]]:
    """Check an address body; return an error dict or None. Normalises in place."""
    problems: Dict[str, str] = {}
    if require_all:
        for key in _ADDRESS_REQUIRED:
            if not str(fields.get(key) or "").strip():
                problems[key] = "required"
    for key in ("phone", "alternatePhone"):
        if fields.get(key):
            digits = re.sub(r"[\s\-+]", "", str(fields[key]))
            digits = digits[-10:] if digits.startswith("91") and len(digits) == 12 else digits
            if not re.fullmatch(r"[6-9]\d{9}", digits):
                problems[key] = "must be a 10-digit mobile number"
            else:
                fields[key] = digits
    if fields.get("pincode") and not re.fullmatch(r"\d{6}", str(fields["pincode"]).strip()):
        problems["pincode"] = "must be 6 digits"
    elif fields.get("pincode"):
        fields["pincode"] = str(fields["pincode"]).strip()
    if fields.get("addressType"):
        fields["addressType"] = str(fields["addressType"]).strip().lower()
        if fields["addressType"] not in _ADDRESS_TYPES:
            problems["addressType"] = "must be home or work"
    if problems:
        return {
            "error": "invalid_address",
            "message": "Ask the user to correct these fields.",
            "fields": problems,
        }
    return None


class AddressTools(_EcomToolBase):
    """Shopper delivery addresses and delivery-charge lookup."""

    @tool(context=True, name="ecom_add_address")
    def add_address(self, address: Dict[str, Any], tool_context: ToolContext) -> Any:
        """Add a delivery address for the signed-in user.

        PUT /user-address (auth).

        Args:
            address: {"name", "phone", "pincode", "addressLine1", "city" (all
                required), "area", "state", "landMark", "additionalInfo",
                "alternatePhone", "addressType": "home"|"work"}. userId is added
                automatically.
        """
        body = dict(address or {})
        invalid = _validate_address(body, require_all=True)
        if invalid:
            return invalid
        user = self._data(tool_context).get(self.AUTH_STATE_KEY, {}).get("user") or {}
        user_id = user.get("_id") or user.get("id")
        if user_id:
            body["userId"] = user_id
        body.setdefault("addressType", "home")
        return self._call(tool_context, "PUT", "/user-address", payload=body)

    @tool(context=True, name="ecom_update_address")
    def update_address(
        self, address_id: str, updates: Dict[str, Any], tool_context: ToolContext
    ) -> Any:
        """Update a saved address.

        PATCH /user-address/:addressId (auth).

        Args:
            address_id: Target address id.
            updates: Partial address fields to change.
        """
        changes = {k: v for k, v in (updates or {}).items() if k not in _ADDRESS_LOCKED}
        if not changes:
            return {
                "error": "no_updates",
                "message": "Provide at least one address field to change.",
            }
        invalid = _validate_address(changes, require_all=False)
        if invalid:
            return invalid
        # The web app PATCHes the whole address, so merge onto the saved copy.
        payload = {**(self._find_address(tool_context, address_id) or {}), **changes}
        return self._call(
            tool_context, "PATCH", f"/user-address/{address_id}", payload=payload
        )

    def _find_address(
        self, tool_context: ToolContext, address_id: str
    ) -> Optional[Dict[str, Any]]:
        listing = self.get_addresses._tool_func(tool_context)
        rows = listing
        while isinstance(rows, dict):
            if "error" in rows:
                return None
            rows = next(
                (rows[k] for k in ("data", "addresses", "result") if k in rows), None
            )
        for row in rows if isinstance(rows, list) else []:
            if isinstance(row, dict) and str(row.get("_id") or row.get("id")) == str(
                address_id
            ):
                return row
        return None

    @tool(context=True, name="ecom_delete_address")
    def delete_address(self, address_id: str, tool_context: ToolContext) -> Any:
        """Delete a saved address.

        DELETE /user-address/:addressId (auth).

        Args:
            address_id: Target address id.
        """
        return self._call(tool_context, "DELETE", f"/user-address/{address_id}")

    @tool(context=True, name="ecom_get_addresses")
    def get_addresses(self, tool_context: ToolContext) -> Any:
        """List the signed-in user's saved addresses.

        GET /user-address?userId=<id> (auth) — the web app always sends userId.
        """
        user = self._data(tool_context).get(self.AUTH_STATE_KEY, {}).get("user") or {}
        user_id = user.get("_id") or user.get("id")
        params = {"userId": user_id} if user_id else None
        return self._call(tool_context, "GET", "/user-address", params=params)

    @tool(context=True, name="ecom_get_default_address")
    def get_default_address(self, tool_context: ToolContext) -> Any:
        """Get the signed-in user's default delivery address.

        GET /my-default-address (auth).
        """
        return self._call(tool_context, "GET", "/my-default-address")

    @tool(context=True, name="ecom_get_delivery_charges")
    def get_delivery_charges(
        self, payload: Dict[str, Any], tool_context: ToolContext
    ) -> Any:
        """Calculate delivery charges for a cart/address.

        POST /delivery-charges (auth).

        Args:
            payload: e.g. {"addressId": "...", "shopId": "...", "items": [...]}.
        """
        return self._call(
            tool_context, "POST", "/delivery-charges", payload=payload
        )


# ─────────────────────────────────────────────────────────────────────────────
# AWS uploads
# ─────────────────────────────────────────────────────────────────────────────


class UploadTools(_EcomToolBase):
    """Presigned S3 upload keys and file cleanup."""

    @tool(context=True, name="ecom_get_upload_keys")
    def get_upload_keys(
        self, payload: Dict[str, Any], tool_context: ToolContext
    ) -> Any:
        """Get presigned S3 keys/URLs for uploading files.

        POST /upload-keys (auth).

        Args:
            payload: e.g. {"files": [{"name": "a.jpg", "type": "image/jpeg"}]}.
        """
        return self._call(tool_context, "POST", "/upload-keys", payload=payload)

    @tool(context=True, name="ecom_remove_files")
    def remove_files(
        self, payload: Dict[str, Any], tool_context: ToolContext
    ) -> Any:
        """Remove previously uploaded files.

        PATCH /remove-files (auth).

        Args:
            payload: e.g. {"keys": ["uploads/a.jpg"]}.
        """
        return self._call(tool_context, "PATCH", "/remove-files", payload=payload)


# ─────────────────────────────────────────────────────────────────────────────
# Categories & sub-categories
# ─────────────────────────────────────────────────────────────────────────────


class CategoryTools(_EcomToolBase):
    """Product categories and sub-categories."""

    @tool(context=True, name="ecom_add_category")
    def add_category(self, category: Dict[str, Any], tool_context: ToolContext) -> Any:
        """Create a category.

        PUT /categories (auth).

        Args:
            category: Category body (name, image, position, …).
        """
        return self._call(tool_context, "PUT", "/categories", payload=category)

    @tool(context=True, name="ecom_update_category")
    def update_category(
        self, category_id: str, updates: Dict[str, Any], tool_context: ToolContext
    ) -> Any:
        """Update a category.

        PATCH /categories/:id (auth).

        Args:
            category_id: Target category id.
            updates: Partial category fields.
        """
        return self._call(
            tool_context, "PATCH", f"/categories/{category_id}", payload=updates
        )

    @tool(context=True, name="ecom_delete_category")
    def delete_category(self, category_id: str, tool_context: ToolContext) -> Any:
        """Delete a category.

        DELETE /categories/:id (auth).

        Args:
            category_id: Target category id.
        """
        return self._call(tool_context, "DELETE", f"/categories/{category_id}")

    @tool(name="ecom_search_categories")
    def search_categories(self, filters: Optional[Dict[str, Any]] = None) -> Any:
        """Search / list categories.

        GET /categories (public).

        Args:
            filters: Query params, e.g. {"search": "...", "shopId": "..."}.
        """
        return self._call(None, "GET", "/categories", auth=False, params=filters)

    @tool(name="ecom_search_shop_categories")
    def search_shop_categories(self, filters: Optional[Dict[str, Any]] = None) -> Any:
        """List all categories for a shop context.

        GET /getall/categories (public).

        Args:
            filters: Query params, e.g. {"shopId": "..."}.
        """
        return self._call(None, "GET", "/getall/categories", auth=False, params=filters)

    @tool(context=True, name="ecom_add_sub_category")
    def add_sub_category(
        self, sub_category: Dict[str, Any], tool_context: ToolContext
    ) -> Any:
        """Create a sub-category.

        PUT /sub-categories (auth).

        Args:
            sub_category: Sub-category body (name, categoryId, …).
        """
        return self._call(
            tool_context, "PUT", "/sub-categories", payload=sub_category
        )

    @tool(context=True, name="ecom_update_sub_category")
    def update_sub_category(
        self, sub_category_id: str, updates: Dict[str, Any], tool_context: ToolContext
    ) -> Any:
        """Update a sub-category.

        PATCH /sub-categories/:id (auth).

        Args:
            sub_category_id: Target sub-category id.
            updates: Partial fields.
        """
        return self._call(
            tool_context,
            "PATCH",
            f"/sub-categories/{sub_category_id}",
            payload=updates,
        )

    @tool(context=True, name="ecom_delete_sub_category")
    def delete_sub_category(
        self, sub_category_id: str, tool_context: ToolContext
    ) -> Any:
        """Delete a sub-category.

        DELETE /sub-categories/:id (auth).

        Args:
            sub_category_id: Target sub-category id.
        """
        return self._call(
            tool_context, "DELETE", f"/sub-categories/{sub_category_id}"
        )

    @tool(name="ecom_search_sub_categories")
    def search_sub_categories(self, filters: Optional[Dict[str, Any]] = None) -> Any:
        """Search / list sub-categories.

        GET /sub-categories (public).

        Args:
            filters: Query params, e.g. {"categoryId": "..."}.
        """
        return self._call(None, "GET", "/sub-categories", auth=False, params=filters)

    @tool(name="ecom_search_categories_with_sub")
    def search_categories_with_sub(
        self, filters: Optional[Dict[str, Any]] = None
    ) -> Any:
        """List categories together with their sub-categories.

        GET /categories-sub-categories (public).

        Args:
            filters: Query params.
        """
        return self._call(
            None, "GET", "/categories-sub-categories", auth=False, params=filters
        )

    @tool(name="ecom_get_sub_categories_by_category")
    def get_sub_categories_by_category(
        self, category_id: str, filters: Optional[Dict[str, Any]] = None
    ) -> Any:
        """Get sub-categories for a given category id.

        GET /sub-categories/:type (public) — ``:type`` is the category id.

        Args:
            category_id: Parent category id.
            filters: Optional query params.
        """
        return self._call(
            None, "GET", f"/sub-categories/{category_id}", auth=False, params=filters
        )


# ─────────────────────────────────────────────────────────────────────────────
# Products, product options & cart
# ─────────────────────────────────────────────────────────────────────────────


class ProductTools(_EcomToolBase):
    """Product catalogue, product options, and the shopping cart."""

    @tool(context=True, name="ecom_add_product")
    def add_product(self, product: Dict[str, Any], tool_context: ToolContext) -> Any:
        """Create a product.

        PUT /products (auth).

        Args:
            product: Product body (name, price, categoryId, images, …).
        """
        return self._call(tool_context, "PUT", "/products", payload=product)

    @tool(context=True, name="ecom_update_product")
    def update_product(
        self, product_id: str, updates: Dict[str, Any], tool_context: ToolContext
    ) -> Any:
        """Update a product.

        PATCH /products/:id (auth).

        Args:
            product_id: Target product id.
            updates: Partial product fields.
        """
        return self._call(
            tool_context, "PATCH", f"/products/{product_id}", payload=updates
        )

    @tool(context=True, name="ecom_delete_product")
    def delete_product(self, product_id: str, tool_context: ToolContext) -> Any:
        """Delete a product.

        DELETE /products/:id (auth).

        Args:
            product_id: Target product id.
        """
        return self._call(tool_context, "DELETE", f"/products/{product_id}")

    @tool(name="ecom_search_products")
    def search_products(self, filters: Optional[Dict[str, Any]] = None) -> Any:
        """Search / list products.

        POST /products (public).

        Args:
            filters: Search body, e.g.
                {"search": "milk", "categoryId": "...", "shopId": "...",
                 "sort": "price", "page": 1, "limit": 20}.
        """
        return self._call(None, "POST", "/products", auth=False, payload=filters or {})

    @tool(name="ecom_search_products_by_address")
    def search_products_by_address(self, payload: Dict[str, Any]) -> Any:
        """Search products available for a delivery address / location.

        POST /search-products (public).

        Args:
            payload: e.g. {"lat": .., "lng": .., "search": "...", "page": 1}.
        """
        return self._call(
            None, "POST", "/search-products", auth=False, payload=payload
        )

    @tool(name="ecom_get_shop_products")
    def get_shop_products(
        self, shop_id: str, filters: Optional[Dict[str, Any]] = None
    ) -> Any:
        """List a shop's products.

        GET /shops/:shopId/products (public).

        Args:
            shop_id: Target shop id.
            filters: Optional query params (page, limit, categoryId, …).
        """
        return self._call(
            None, "GET", f"/shops/{shop_id}/products", auth=False, params=filters
        )

    @tool(name="ecom_get_product_details")
    def get_product_details(self, product_id: str) -> Any:
        """Get one product's full details.

        GET /products/:productId (public).

        Args:
            product_id: Target product id.
        """
        return self._call(None, "GET", f"/products/{product_id}", auth=False)

    @tool(context=True, name="ecom_add_product_options")
    def add_product_options(
        self, product_id: str, options: Dict[str, Any], tool_context: ToolContext
    ) -> Any:
        """Add options (variants/add-ons) to a product.

        PUT /products/:productId/options (auth).

        Args:
            product_id: Target product id.
            options: Option body.
        """
        return self._call(
            tool_context,
            "PUT",
            f"/products/{product_id}/options",
            payload=options,
        )

    @tool(name="ecom_get_product_options")
    def get_product_options(self, product_id: str) -> Any:
        """Get a product's options.

        GET /products/:productId/options (public).

        Args:
            product_id: Target product id.
        """
        return self._call(
            None, "GET", f"/products/{product_id}/options", auth=False
        )

    @tool(context=True, name="ecom_update_product_options")
    def update_product_options(
        self,
        product_id: str,
        option_id: str,
        updates: Dict[str, Any],
        tool_context: ToolContext,
    ) -> Any:
        """Update a product option.

        PATCH /products/:productId/options/:id (auth).

        Args:
            product_id: Target product id.
            option_id: Target option id.
            updates: Partial option fields.
        """
        return self._call(
            tool_context,
            "PATCH",
            f"/products/{product_id}/options/{option_id}",
            payload=updates,
        )

    @tool(context=True, name="ecom_delete_product_options")
    def delete_product_options(
        self, product_id: str, option_id: str, tool_context: ToolContext
    ) -> Any:
        """Delete a product option.

        DELETE /products/:productId/options/:id (auth).

        Args:
            product_id: Target product id.
            option_id: Target option id.
        """
        return self._call(
            tool_context,
            "DELETE",
            f"/products/{product_id}/options/{option_id}",
        )

    # -- cart -----------------------------------------------------------

    @tool(context=True, name="ecom_add_to_cart")
    def add_to_cart(self, item: Dict[str, Any], tool_context: ToolContext) -> Any:
        """Add an item to the signed-in user's cart.

        PUT /carts (auth).

        Args:
            item: e.g. {"productId": "...", "quantity": 2, "optionId": "..."}.
        """
        return self._call(tool_context, "PUT", "/carts", payload=item)

    @tool(context=True, name="ecom_remove_from_cart")
    def remove_from_cart(self, cart_item_id: str, tool_context: ToolContext) -> Any:
        """Remove an item from the cart.

        DELETE /carts/:id (auth).

        Args:
            cart_item_id: Cart line-item id.
        """
        return self._call(tool_context, "DELETE", f"/carts/{cart_item_id}")

    @tool(context=True, name="ecom_update_cart")
    def update_cart(
        self, cart_item_id: str, updates: Dict[str, Any], tool_context: ToolContext
    ) -> Any:
        """Update a cart line item (e.g. quantity).

        PATCH /carts/:id (auth).

        Args:
            cart_item_id: Cart line-item id.
            updates: e.g. {"quantity": 3}.
        """
        return self._call(
            tool_context, "PATCH", f"/carts/{cart_item_id}", payload=updates
        )

    @tool(context=True, name="ecom_get_my_cart")
    def get_my_cart(
        self, tool_context: ToolContext, payload: Optional[Dict[str, Any]] = None
    ) -> Any:
        """Get the signed-in user's current cart.

        POST /carts (auth).

        Args:
            payload: Optional body, e.g. {"addressId": "...", "couponCode": "..."}.
        """
        return self._call(tool_context, "POST", "/carts", payload=payload or {})


# ─────────────────────────────────────────────────────────────────────────────
# Banners
# ─────────────────────────────────────────────────────────────────────────────


class BannerTools(_EcomToolBase):
    """Marketing banners."""

    @tool(context=True, name="ecom_add_banner")
    def add_banner(self, banner: Dict[str, Any], tool_context: ToolContext) -> Any:
        """Create a banner.

        PUT /banners (auth).

        Args:
            banner: Banner body (image, position, link, …).
        """
        return self._call(tool_context, "PUT", "/banners", payload=banner)

    @tool(context=True, name="ecom_update_banner")
    def update_banner(
        self, banner_id: str, updates: Dict[str, Any], tool_context: ToolContext
    ) -> Any:
        """Update a banner.

        PATCH /banners/:id (auth).

        Args:
            banner_id: Target banner id.
            updates: Partial banner fields.
        """
        return self._call(
            tool_context, "PATCH", f"/banners/{banner_id}", payload=updates
        )

    @tool(context=True, name="ecom_delete_banner")
    def delete_banner(self, banner_id: str, tool_context: ToolContext) -> Any:
        """Delete a banner.

        DELETE /banners/:id (auth).

        Args:
            banner_id: Target banner id.
        """
        return self._call(tool_context, "DELETE", f"/banners/{banner_id}")

    @tool(name="ecom_search_banners")
    def search_banners(self, filters: Optional[Dict[str, Any]] = None) -> Any:
        """Search / list banners.

        GET /banners (public).

        Args:
            filters: Query params, e.g. {"position": "home_top"}.
        """
        return self._call(None, "GET", "/banners", auth=False, params=filters)

    @tool(name="ecom_get_banner_positions")
    def get_banner_positions(self) -> Any:
        """List the distinct banner positions in use.

        GET /banners-distinct-positions (public).
        """
        return self._call(None, "GET", "/banners-distinct-positions", auth=False)


# ─────────────────────────────────────────────────────────────────────────────
# Location groups
# ─────────────────────────────────────────────────────────────────────────────


class LocationGroupTools(_EcomToolBase):
    """Delivery location groups."""

    @tool(context=True, name="ecom_add_location_group")
    def add_location_group(
        self, location_group: Dict[str, Any], tool_context: ToolContext
    ) -> Any:
        """Create a location group.

        PUT /location-groups (auth).

        Args:
            location_group: Location-group body (name, polygon/areas, …).
        """
        return self._call(
            tool_context, "PUT", "/location-groups", payload=location_group
        )

    @tool(context=True, name="ecom_update_location_group")
    def update_location_group(
        self, group_id: str, updates: Dict[str, Any], tool_context: ToolContext
    ) -> Any:
        """Update a location group.

        PATCH /location-groups/:id (auth).

        Args:
            group_id: Target location-group id.
            updates: Partial fields.
        """
        return self._call(
            tool_context, "PATCH", f"/location-groups/{group_id}", payload=updates
        )

    @tool(context=True, name="ecom_delete_location_group")
    def delete_location_group(self, group_id: str, tool_context: ToolContext) -> Any:
        """Delete a location group.

        DELETE /location-groups/:id (auth).

        Args:
            group_id: Target location-group id.
        """
        return self._call(
            tool_context, "DELETE", f"/location-groups/{group_id}"
        )

    @tool(name="ecom_search_location_groups")
    def search_location_groups(
        self, filters: Optional[Dict[str, Any]] = None
    ) -> Any:
        """Search / list location groups.

        GET /location-groups (public).

        Args:
            filters: Query params.
        """
        return self._call(None, "GET", "/location-groups", auth=False, params=filters)


# ─────────────────────────────────────────────────────────────────────────────
# Payments
# ─────────────────────────────────────────────────────────────────────────────


class PaymentTools(_EcomToolBase):
    """Payment records."""

    @tool(context=True, name="ecom_add_payment")
    def add_payment(self, payment: Dict[str, Any], tool_context: ToolContext) -> Any:
        """Create a payment record.

        PUT /payments (auth).

        Args:
            payment: Payment body.
        """
        return self._call(tool_context, "PUT", "/payments", payload=payment)

    @tool(context=True, name="ecom_update_payment")
    def update_payment(
        self, payment_id: str, updates: Dict[str, Any], tool_context: ToolContext
    ) -> Any:
        """Update a payment record.

        PATCH /payments/:id (auth).

        Args:
            payment_id: Target payment id.
            updates: Partial fields.
        """
        return self._call(
            tool_context, "PATCH", f"/payments/{payment_id}", payload=updates
        )

    @tool(context=True, name="ecom_delete_payment")
    def delete_payment(self, payment_id: str, tool_context: ToolContext) -> Any:
        """Delete a payment record.

        DELETE /payments/:id (auth).

        Args:
            payment_id: Target payment id.
        """
        return self._call(tool_context, "DELETE", f"/payments/{payment_id}")

    @tool(context=True, name="ecom_search_payments")
    def search_payments(
        self, tool_context: ToolContext, filters: Optional[Dict[str, Any]] = None
    ) -> Any:
        """Search / list payment records.

        GET /payments (auth).

        Args:
            filters: Query params.
        """
        return self._call(tool_context, "GET", "/payments", params=filters)


# ─────────────────────────────────────────────────────────────────────────────
# Wishlists
# ─────────────────────────────────────────────────────────────────────────────


class WishlistTools(_EcomToolBase):
    """Wishlists and their items."""

    @tool(context=True, name="ecom_add_wishlist")
    def add_wishlist(self, wishlist: Dict[str, Any], tool_context: ToolContext) -> Any:
        """Create a wishlist.

        PUT /wishlists (auth).

        Args:
            wishlist: Wishlist body (name, …).
        """
        return self._call(tool_context, "PUT", "/wishlists", payload=wishlist)

    @tool(context=True, name="ecom_update_wishlist")
    def update_wishlist(
        self, wishlist_id: str, updates: Dict[str, Any], tool_context: ToolContext
    ) -> Any:
        """Update a wishlist.

        PATCH /wishlists/:id (auth).

        Args:
            wishlist_id: Target wishlist id.
            updates: Partial fields.
        """
        return self._call(
            tool_context, "PATCH", f"/wishlists/{wishlist_id}", payload=updates
        )

    @tool(context=True, name="ecom_delete_wishlist")
    def delete_wishlist(self, wishlist_id: str, tool_context: ToolContext) -> Any:
        """Delete a wishlist.

        DELETE /wishlists/:id (auth).

        Args:
            wishlist_id: Target wishlist id.
        """
        return self._call(tool_context, "DELETE", f"/wishlists/{wishlist_id}")

    @tool(context=True, name="ecom_search_wishlists")
    def search_wishlists(
        self, tool_context: ToolContext, filters: Optional[Dict[str, Any]] = None
    ) -> Any:
        """Search / list wishlists.

        GET /wishlists (auth).

        Args:
            filters: Query params.
        """
        return self._call(tool_context, "GET", "/wishlists", params=filters)

    @tool(context=True, name="ecom_get_my_wishlist")
    def get_my_wishlist(self, user_id: str, tool_context: ToolContext) -> Any:
        """Get a user's wishlist(s).

        GET /my-wishlists/:userId (auth).

        Args:
            user_id: Target user id.
        """
        return self._call(tool_context, "GET", f"/my-wishlists/{user_id}")

    @tool(context=True, name="ecom_add_to_wishlist")
    def add_to_wishlist(
        self, wishlist_id: str, payload: Dict[str, Any], tool_context: ToolContext
    ) -> Any:
        """Add a product to a wishlist.

        PATCH /wishlists/add/:id (auth).

        Args:
            wishlist_id: Target wishlist id.
            payload: e.g. {"productId": "..."}.
        """
        return self._call(
            tool_context, "PATCH", f"/wishlists/add/{wishlist_id}", payload=payload
        )

    @tool(context=True, name="ecom_remove_from_wishlist")
    def remove_from_wishlist(
        self, wishlist_id: str, payload: Dict[str, Any], tool_context: ToolContext
    ) -> Any:
        """Remove a product from a wishlist.

        PATCH /wishlists/remove/:id (auth).

        Args:
            wishlist_id: Target wishlist id.
            payload: e.g. {"productId": "..."}.
        """
        return self._call(
            tool_context,
            "PATCH",
            f"/wishlists/remove/{wishlist_id}",
            payload=payload,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Orders
# ─────────────────────────────────────────────────────────────────────────────


class OrderTools(_EcomToolBase):
    """Order creation, placement, tracking, and cancellation."""

    @tool(context=True, name="ecom_add_order")
    def add_order(self, order: Dict[str, Any], tool_context: ToolContext) -> Any:
        """Create an order draft.

        PUT /orders (auth).

        Args:
            order: Order body.
        """
        return self._call(tool_context, "PUT", "/orders", payload=order)

    @tool(context=True, name="ecom_place_order")
    def place_order(self, order: Dict[str, Any], tool_context: ToolContext) -> Any:
        """Place an order (checkout).

        POST /place-orders (auth).

        Args:
            order: Checkout body, e.g.
                {"addressId": "...", "paymentMethod": "COD", "couponCode": "...",
                 "items": [...]}.
        """
        return self._call(tool_context, "POST", "/place-orders", payload=order)

    @tool(context=True, name="ecom_update_order")
    def update_order(
        self, order_id: str, updates: Dict[str, Any], tool_context: ToolContext
    ) -> Any:
        """Update an order (e.g. status).

        PATCH /orders/:id (auth).

        Args:
            order_id: Target order id.
            updates: Partial fields, e.g. {"status": "PACKED"}.
        """
        return self._call(
            tool_context, "PATCH", f"/orders/{order_id}", payload=updates
        )

    @tool(context=True, name="ecom_delete_order")
    def delete_order(self, order_id: str, tool_context: ToolContext) -> Any:
        """Delete an order.

        DELETE /orders/:id (auth).

        Args:
            order_id: Target order id.
        """
        return self._call(tool_context, "DELETE", f"/orders/{order_id}")

    @tool(context=True, name="ecom_search_orders")
    def search_orders(
        self, tool_context: ToolContext, filters: Optional[Dict[str, Any]] = None
    ) -> Any:
        """Search / list orders (admin view).

        GET /orders (auth).

        Args:
            filters: Query params, e.g. {"status": "PLACED", "page": 1}.
        """
        return self._call(tool_context, "GET", "/orders", params=filters)

    @tool(context=True, name="ecom_get_my_orders")
    def get_my_orders(
        self, tool_context: ToolContext, filters: Optional[Dict[str, Any]] = None
    ) -> Any:
        """List the signed-in user's own orders.

        GET /my-orders (auth).

        Args:
            filters: Query params, e.g. {"page": 1, "limit": 10}.
        """
        return self._call(tool_context, "GET", "/my-orders", params=filters)

    @tool(context=True, name="ecom_search_deliveryboy_orders")
    def search_deliveryboy_orders(
        self, payload: Dict[str, Any], tool_context: ToolContext
    ) -> Any:
        """List orders assigned to a delivery agent.

        POST /orders-for-deliveryboy (auth).

        Args:
            payload: Filter body, e.g. {"status": "OUT_FOR_DELIVERY"}.
        """
        return self._call(
            tool_context, "POST", "/orders-for-deliveryboy", payload=payload
        )

    @tool(context=True, name="ecom_get_order_details")
    def get_order_details(self, order_id: str, tool_context: ToolContext) -> Any:
        """Get one order's full details.

        GET /order-details/:id (auth).

        Args:
            order_id: Target order id.
        """
        return self._call(tool_context, "GET", f"/order-details/{order_id}")

    @tool(context=True, name="ecom_cancel_order_by_customer")
    def cancel_order_by_customer(
        self, order_id: str, payload: Dict[str, Any], tool_context: ToolContext
    ) -> Any:
        """Cancel an order as the customer.

        POST /orders/:id/cancel-by-customer (auth).

        Args:
            order_id: Target order id.
            payload: e.g. {"reason": "..."}.
        """
        return self._call(
            tool_context,
            "POST",
            f"/orders/{order_id}/cancel-by-customer",
            payload=payload,
        )

    @tool(context=True, name="ecom_reject_cancel_order_by_admin")
    def reject_cancel_order_by_admin(
        self, order_id: str, payload: Dict[str, Any], tool_context: ToolContext
    ) -> Any:
        """Approve or reject a customer cancellation request as an admin.

        POST /orders/:id/reject-cancel-by-admin (auth).

        Args:
            order_id: Target order id.
            payload: e.g. {"action": "reject", "reason": "..."}.
        """
        return self._call(
            tool_context,
            "POST",
            f"/orders/{order_id}/reject-cancel-by-admin",
            payload=payload,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Home feed
# ─────────────────────────────────────────────────────────────────────────────


class HomeFeedTools(_EcomToolBase):
    """Home-feed sections."""

    @tool(context=True, name="ecom_add_home_feed")
    def add_home_feed(self, home_feed: Dict[str, Any], tool_context: ToolContext) -> Any:
        """Create a home-feed section.

        PUT /home-feeds (auth).

        Args:
            home_feed: Home-feed body (title, type, items/query, position, …).
        """
        return self._call(tool_context, "PUT", "/home-feeds", payload=home_feed)

    @tool(context=True, name="ecom_update_home_feed")
    def update_home_feed(
        self, home_feed_id: str, updates: Dict[str, Any], tool_context: ToolContext
    ) -> Any:
        """Update a home-feed section.

        PATCH /home-feeds/:id (auth).

        Args:
            home_feed_id: Target home-feed id.
            updates: Partial fields.
        """
        return self._call(
            tool_context, "PATCH", f"/home-feeds/{home_feed_id}", payload=updates
        )

    @tool(context=True, name="ecom_delete_home_feed")
    def delete_home_feed(self, home_feed_id: str, tool_context: ToolContext) -> Any:
        """Delete a home-feed section.

        DELETE /home-feeds/:id (auth).

        Args:
            home_feed_id: Target home-feed id.
        """
        return self._call(tool_context, "DELETE", f"/home-feeds/{home_feed_id}")

    @tool(name="ecom_search_home_feeds")
    def search_home_feeds(self, filters: Optional[Dict[str, Any]] = None) -> Any:
        """Search / list home-feed sections.

        GET /home-feeds (public).

        Args:
            filters: Query params, e.g. {"lat": .., "lng": ..}.
        """
        return self._call(None, "GET", "/home-feeds", auth=False, params=filters)


# ─────────────────────────────────────────────────────────────────────────────
# Dashboard
# ─────────────────────────────────────────────────────────────────────────────


class DashboardTools(_EcomToolBase):
    """Admin dashboard aggregates."""

    @tool(context=True, name="ecom_get_dashboard_data")
    def get_dashboard_data(
        self, tool_context: ToolContext, filters: Optional[Dict[str, Any]] = None
    ) -> Any:
        """Get top-level dashboard metrics.

        GET /dashboard-data (auth).

        Args:
            filters: Query params, e.g. {"from": "2026-01-01", "to": "2026-01-31"}.
        """
        return self._call(tool_context, "GET", "/dashboard-data", params=filters)

    @tool(context=True, name="ecom_get_orders_dashboard_data")
    def get_orders_dashboard_data(
        self, tool_context: ToolContext, filters: Optional[Dict[str, Any]] = None
    ) -> Any:
        """Get order-focused dashboard metrics.

        GET /dashboard-data/orders (auth).

        Args:
            filters: Query params.
        """
        return self._call(
            tool_context, "GET", "/dashboard-data/orders", params=filters
        )


# ─────────────────────────────────────────────────────────────────────────────
# Razorpay
# ─────────────────────────────────────────────────────────────────────────────


class RazorpayTools(_EcomToolBase):
    """Razorpay payment gateway operations."""

    @tool(context=True, name="ecom_create_razorpay_order")
    def create_razorpay_order(
        self, payload: Dict[str, Any], tool_context: ToolContext
    ) -> Any:
        """Create a Razorpay order for a checkout.

        PUT /razorpay/order (auth).

        Args:
            payload: e.g. {"amount": 49900, "currency": "INR", "orderId": "..."}.
        """
        return self._call(tool_context, "PUT", "/razorpay/order", payload=payload)

    @tool(context=True, name="ecom_verify_razorpay_payment")
    def verify_razorpay_payment(
        self, payload: Dict[str, Any], tool_context: ToolContext
    ) -> Any:
        """Verify a Razorpay payment signature after checkout.

        POST /razorpay/verify-payment-signature (auth).

        Args:
            payload: {"razorpay_order_id": ..., "razorpay_payment_id": ...,
                      "razorpay_signature": ...}.
        """
        return self._call(
            tool_context,
            "POST",
            "/razorpay/verify-payment-signature",
            payload=payload,
        )

    @tool(context=True, name="ecom_capture_razorpay_payment")
    def capture_razorpay_payment(
        self, payload: Dict[str, Any], tool_context: ToolContext
    ) -> Any:
        """Capture an authorised Razorpay payment.

        POST /razorpay/capture-a-payment (auth).

        Args:
            payload: {"paymentId": ..., "amount": ...}.
        """
        return self._call(
            tool_context, "POST", "/razorpay/capture-a-payment", payload=payload
        )


# ─────────────────────────────────────────────────────────────────────────────
# Coupons
# ─────────────────────────────────────────────────────────────────────────────


class CouponTools(_EcomToolBase):
    """Discount coupons."""

    @tool(context=True, name="ecom_add_coupon")
    def add_coupon(self, coupon: Dict[str, Any], tool_context: ToolContext) -> Any:
        """Create a coupon.

        PUT /coupons (auth).

        Args:
            coupon: Coupon body (code, type, value, minOrder, expiry, …).
        """
        return self._call(tool_context, "PUT", "/coupons", payload=coupon)

    @tool(context=True, name="ecom_update_coupon")
    def update_coupon(
        self, coupon_id: str, updates: Dict[str, Any], tool_context: ToolContext
    ) -> Any:
        """Update a coupon.

        PATCH /coupons/:id (auth).

        Args:
            coupon_id: Target coupon id.
            updates: Partial fields.
        """
        return self._call(
            tool_context, "PATCH", f"/coupons/{coupon_id}", payload=updates
        )

    @tool(context=True, name="ecom_delete_coupon")
    def delete_coupon(self, coupon_id: str, tool_context: ToolContext) -> Any:
        """Delete a coupon.

        DELETE /coupons/:id (auth).

        Args:
            coupon_id: Target coupon id.
        """
        return self._call(tool_context, "DELETE", f"/coupons/{coupon_id}")

    @tool(context=True, name="ecom_search_coupons")
    def search_coupons(
        self, tool_context: ToolContext, filters: Optional[Dict[str, Any]] = None
    ) -> Any:
        """Search / list coupons.

        GET /coupons (auth).

        Args:
            filters: Query params.
        """
        return self._call(tool_context, "GET", "/coupons", params=filters)

    @tool(context=True, name="ecom_validate_coupon")
    def validate_coupon(
        self, payload: Dict[str, Any], tool_context: ToolContext
    ) -> Any:
        """Validate a coupon code against the current cart/order.

        POST /coupons/validate (auth).

        Args:
            payload: e.g. {"code": "SAVE10", "cartTotal": 500, "items": [...]}.
        """
        return self._call(
            tool_context, "POST", "/coupons/validate", payload=payload
        )


# ─────────────────────────────────────────────────────────────────────────────
# Flow control (terminal-state signalling for transactional agents)
# ─────────────────────────────────────────────────────────────────────────────


class FlowControlTools(_EcomToolBase):
    """Lets a transactional specialist tell the orchestrator it is finished."""

    @tool(context=True, name="commerce_complete_task")
    def complete_task(
        self, summary: str, tool_context: ToolContext, order_id: str = ""
    ) -> Any:
        """Call this ONLY once the task is fully done (order placed, order
        cancelled, …). Records a terminal COMPLETE status the orchestrator acts on.

        Args:
            summary: One-sentence, user-facing summary of what was done.
            order_id: The order id, when the task produced or acted on one.
        """
        data = self._data(tool_context)
        data["status"] = "COMPLETE"
        data["task_summary"] = summary
        if order_id:
            data["order_id"] = order_id
        tool_context.agent.state.set("data", data)
        self.logger.info(f"[flow] task COMPLETE — {summary}")
        return {"status": "COMPLETE", "summary": summary, "order_id": order_id or None}

    @tool(context=True, name="commerce_fail_task")
    def fail_task(self, reason: str, tool_context: ToolContext) -> Any:
        """Call this when the task cannot be completed and should not be retried
        automatically. Records a terminal FAILED status.

        Args:
            reason: One-sentence, user-facing reason.
        """
        data = self._data(tool_context)
        data["status"] = "FAILED"
        data["task_summary"] = reason
        tool_context.agent.state.set("data", data)
        self.logger.warning(f"[flow] task FAILED — {reason}")
        return {"status": "FAILED", "reason": reason}


# ─────────────────────────────────────────────────────────────────────────────
# Aggregator + per-agent tool selectors
# ─────────────────────────────────────────────────────────────────────────────


ECOMMERCE_TOOL_GROUPS = (
    UserAuthTools,
    ShopTools,
    AddressTools,
    UploadTools,
    CategoryTools,
    ProductTools,
    BannerTools,
    LocationGroupTools,
    PaymentTools,
    WishlistTools,
    OrderTools,
    HomeFeedTools,
    DashboardTools,
    RazorpayTools,
    CouponTools,
    FlowControlTools,
)


def build_ecommerce_toolset(logger_config) -> List[Any]:
    """Instantiate every tool group and return a flat list of Strands tools.

    Mostly useful for tests / introspection. Real agents take a curated
    subset via the selector helpers below.
    """
    tools: List[Any] = []
    for group_cls in ECOMMERCE_TOOL_GROUPS:
        tools.extend(group_cls(logger_config).tools())
    return tools


def _pick(instance: _EcomToolBase, *method_names: str) -> List[Any]:
    """Return the named ``@tool`` methods off a group instance, in order."""
    picked = []
    for name in method_names:
        attr = getattr(instance, name)
        if not hasattr(attr, "tool_spec"):
            raise AttributeError(f"{type(instance).__name__}.{name} is not a @tool")
        picked.append(attr)
    return picked


class ToolBundle:
    """
    A curated set of tools for one specialist agent.

    Holds strong references to the underlying group instances (so their
    bound ``@tool`` methods stay alive for the agent's lifetime) and
    exposes the flat ``tools`` list to pass to ``Agent(tools=...)``.
    """

    def __init__(self, groups: List[_EcomToolBase], tools: List[Any]):
        self._groups = groups
        self.tools = tools

    def names(self) -> List[str]:
        return [t.tool_name for t in self.tools]


def auth_tools(logger_config) -> ToolBundle:
    ua = UserAuthTools(logger_config)
    return ToolBundle(
        [ua],
        _pick(
            ua,
            "login",
            "login_social",
            "register_user",
            "forgot_password",
            "verify_email",
            "resend_verification",
        ),
    )


def browse_tools(logger_config) -> ToolBundle:
    prod = ProductTools(logger_config)
    cat = CategoryTools(logger_config)
    shop = ShopTools(logger_config)
    banner = BannerTools(logger_config)
    feed = HomeFeedTools(logger_config)
    return ToolBundle(
        [prod, cat, shop, banner, feed],
        [
            *_pick(
                prod,
                "search_products",
                "search_products_by_address",
                "get_product_details",
                "get_product_options",
                "get_shop_products",
            ),
            *_pick(
                cat,
                "search_categories",
                "search_shop_categories",
                "search_sub_categories",
                "search_categories_with_sub",
                "get_sub_categories_by_category",
            ),
            *_pick(shop, "search_shops"),
            *_pick(banner, "search_banners"),
            *_pick(feed, "search_home_feeds"),
        ],
    )


def cart_tools(logger_config) -> ToolBundle:
    """Cart management plus the checkout flow (CartAgent owns both)."""
    prod = ProductTools(logger_config)
    addr = AddressTools(logger_config)
    coupon = CouponTools(logger_config)
    order = OrderTools(logger_config)
    rzp = RazorpayTools(logger_config)
    flow = FlowControlTools(logger_config)
    return ToolBundle(
        [prod, addr, coupon, order, rzp, flow],
        [
            *_pick(
                prod,
                "get_my_cart",
                "add_to_cart",
                "update_cart",
                "remove_from_cart",
                "get_product_details",
                "get_product_options",
            ),
            *_pick(
                addr,
                "get_addresses",
                "get_default_address",
                "add_address",
                "get_delivery_charges",
            ),
            *_pick(coupon, "validate_coupon"),
            *_pick(order, "place_order"),
            *_pick(
                rzp,
                "create_razorpay_order",
                "verify_razorpay_payment",
                "capture_razorpay_payment",
            ),
            *_pick(flow, "complete_task", "fail_task"),
        ],
    )


def account_tools(logger_config) -> ToolBundle:
    addr = AddressTools(logger_config)
    wish = WishlistTools(logger_config)
    ua = UserAuthTools(logger_config)
    flow = FlowControlTools(logger_config)
    return ToolBundle(
        [addr, wish, ua, flow],
        [
            *_pick(
                addr,
                "get_addresses",
                "add_address",
                "update_address",
                "delete_address",
                "get_default_address",
            ),
            *_pick(
                wish,
                "get_my_wishlist",
                "search_wishlists",
                "add_wishlist",
                "add_to_wishlist",
                "remove_from_wishlist",
            ),
            *_pick(ua, "get_user_details", "verify_account_email", "update_my_profile"),
            *_pick(flow, "complete_task", "fail_task"),
        ],
    )
