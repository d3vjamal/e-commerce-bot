"""Order operations on top of the generic REST client.

Flow: OrderAgent → order tools (``tools/order_tools.py``) → ``OrderService`` →
``EcommerceService.request`` → Express API. Every method returns an
``ApiResponse`` so callers never see raw exceptions.
"""

from typing import Any, Dict, Optional

from services.ecommerce_service import EcommerceService
from utils.logger import Logger
from utils.response import ApiResponse, ResponseBuilder

#: delivery details a customer may change on their own order. Status and
#: payment fields are staff-only and rejected here.
CUSTOMER_EDITABLE_FIELDS = frozenset(
    {
        "addressId",
        "address",
        "deliveryAddress",
        "phone",
        "contactNumber",
        "note",
        "notes",
        "deliveryInstructions",
    }
)

#: once an order reaches one of these, the customer can no longer modify or
#: cancel it (best-effort pre-check; the backend remains the authority)
LOCKED_STATUSES = frozenset(
    {"SHIPPED", "OUT_FOR_DELIVERY", "DELIVERED", "CANCELLED", "CANCELED", "RETURNED"}
)


def find_status(body: Any) -> Optional[str]:
    """Pull an order status out of a response body of unknown nesting."""
    if not isinstance(body, dict):
        return None
    for key in ("status", "orderStatus"):
        value = body.get(key)
        if isinstance(value, str) and value:
            return value.upper()
    for container in ("data", "order", "result"):
        found = find_status(body.get(container))
        if found:
            return found
    return None


class OrderService:
    def __init__(self, logger_config, api: Optional[EcommerceService] = None):
        self.logger = Logger(__name__, logger_config)
        self.api = api or EcommerceService(logger_config)
        self.responses = ResponseBuilder(logger_config)

    def _call(self, method: str, path: str, token: str, **kwargs) -> ApiResponse:
        try:
            body = self.api.request(method, path, token=token, **kwargs)
        except Exception as exc:  # noqa: BLE001 — logged by handle_errors
            return self.responses.from_exception(exc)
        return self.responses.ok(body)

    def list_my_orders(
        self, token: str, filters: Optional[Dict[str, Any]] = None
    ) -> ApiResponse:
        """GET /my-orders"""
        return self._call("GET", "/my-orders", token, params=filters)

    def get_order(self, token: str, order_id: str) -> ApiResponse:
        """GET /order-details/:id — full detail, status and tracking."""
        return self._call("GET", f"/order-details/{order_id}", token)

    def _ensure_changeable(self, token: str, order_id: str) -> Optional[ApiResponse]:
        """Return a failure response if the order can no longer be changed."""
        details = self.get_order(token, order_id)
        if not details.success:
            return details
        status = find_status(details.data)
        if status in LOCKED_STATUSES:
            return self.responses.fail(
                "order_not_changeable",
                message=f"This order is {status} and can no longer be changed.",
                data={"status": status},
            )
        return None

    def modify_order(
        self, token: str, order_id: str, updates: Dict[str, Any]
    ) -> ApiResponse:
        """PATCH /orders/:id — delivery details only."""
        rejected = sorted(set(updates) - CUSTOMER_EDITABLE_FIELDS)
        if rejected or not updates:
            return self.responses.fail(
                "fields_not_allowed" if rejected else "no_updates",
                message="Only delivery details can be changed.",
                data={"rejected": rejected, "allowed": sorted(CUSTOMER_EDITABLE_FIELDS)},
            )
        blocked = self._ensure_changeable(token, order_id)
        if blocked:
            return blocked
        return self._call("PATCH", f"/orders/{order_id}", token, payload=updates)

    def cancel_order(
        self, token: str, order_id: str, reason: str
    ) -> ApiResponse:
        """POST /orders/:id/cancel-by-customer"""
        blocked = self._ensure_changeable(token, order_id)
        if blocked:
            return blocked
        return self._call(
            "POST",
            f"/orders/{order_id}/cancel-by-customer",
            token,
            payload={"reason": reason},
        )
