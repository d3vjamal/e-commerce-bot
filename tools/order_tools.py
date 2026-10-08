"""Strands tools for the OrderAgent. Thin: resolve the session token, call
``OrderService``, return the ``ApiResponse`` as a dict for the LLM."""

from typing import Any, Dict, Optional

from strands import ToolContext, tool

from services.order_service import CUSTOMER_EDITABLE_FIELDS, OrderService
from tools.ecommerce_tools import (
    AddressTools,
    FlowControlTools,
    ProductTools,
    ToolBundle,
    _EcomToolBase,
    _pick,
)
from utils.response import ResponseBuilder

_NOT_AUTH = {
    "success": False,
    "error": "not_authenticated",
    "message": "The user must sign in before this action.",
}


class OrderAgentTools(_EcomToolBase):
    def __init__(self, logger_config):
        super().__init__(logger_config)
        self.orders = OrderService(logger_config)

    def _run(self, tool_context: ToolContext, fn, *args) -> Any:
        token = self._token(tool_context)
        if not token:
            return _NOT_AUTH
        return fn(token, *args).to_dict()

    @tool(context=True, name="ecom_get_my_orders")
    def get_my_orders(
        self, tool_context: ToolContext, filters: Optional[Dict[str, Any]] = None
    ) -> Any:
        """List the signed-in user's own orders.

        Args:
            filters: Query params, e.g. {"page": 1, "limit": 10}.
        """
        return self._run(tool_context, self.orders.list_my_orders, filters)

    @tool(context=True, name="ecom_get_order_details")
    def get_order_details(self, order_id: str, tool_context: ToolContext) -> Any:
        """Get one order's full details, status and tracking.

        Args:
            order_id: Target order id.
        """
        return self._run(tool_context, self.orders.get_order, order_id)

    @tool(context=True, name="ecom_place_order")
    def place_order(self, order: Dict[str, Any], tool_context: ToolContext) -> Any:
        """Place a new order from the user's cart. Call only after the user
        confirmed address, payment method and total.

        Args:
            order: {"addressId": "...", "paymentMethod": "COD"|"ONLINE",
                "couponCode": "...?"}.
        """
        return self._run(tool_context, self.orders.place_order, order)

    @tool(context=True, name="ecom_modify_order_item_quantity")
    def modify_order_item_quantity(
        self, order_id: str, item_id: str, quantity: int, tool_context: ToolContext
    ) -> Any:
        """Change the quantity of one item on the user's own order. Refused if
        the order is already shipped or closed. Quantity must be >= 1 (use
        cancel to remove the whole order).

        Args:
            order_id: The order to modify.
            item_id: The line item id from the order details.
            quantity: New quantity (whole number >= 1).
        """
        return self._run(
            tool_context, self.orders.modify_item_quantity, order_id, item_id, quantity
        )

    @tool(context=True, name="ecom_modify_order_by_customer")
    def modify_order_by_customer(
        self, order_id: str, updates: Dict[str, Any], tool_context: ToolContext
    ) -> Any:
        """Change delivery details (address, phone, notes / delivery
        instructions) on the user's own order. Status and payment cannot be
        changed. Refused if the order is already shipped or closed.

        Args:
            order_id: The order to modify.
            updates: Allowed fields only, e.g. {"deliveryInstructions": "..."}.
        """
        return self._run(tool_context, self.orders.modify_order, order_id, updates)

    @tool(context=True, name="ecom_cancel_order_by_customer")
    def cancel_order_by_customer(
        self,
        order_id: str,
        tool_context: ToolContext,
        reason: str = "Cancelled by customer",
    ) -> Any:
        """Cancel the user's own order. Call only after the user confirmed.
        Refused if the order is already shipped or closed.

        Args:
            order_id: Target order id.
            reason: The user's cancellation reason, if they gave one.
        """
        return self._run(tool_context, self.orders.cancel_order, order_id, reason)


def order_tools(logger_config) -> ToolBundle:
    ot = OrderAgentTools(logger_config)
    prod = ProductTools(logger_config)
    addr = AddressTools(logger_config)
    flow = FlowControlTools(logger_config)
    return ToolBundle(
        [ot, prod, addr, flow],
        [
            ot.get_my_orders,
            ot.get_order_details,
            ot.place_order,
            ot.modify_order_item_quantity,
            ot.modify_order_by_customer,
            ot.cancel_order_by_customer,
            *_pick(prod, "get_my_cart"),
            *_pick(addr, "get_addresses", "get_default_address"),
            flow.complete_task,
            flow.fail_task,
        ],
    )
