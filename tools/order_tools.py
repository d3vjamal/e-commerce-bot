"""Strands tools for the OrderAgent. Thin: resolve the session token, call
``OrderService``, return the ``ApiResponse`` as a dict for the LLM."""

from typing import Any, Dict, Optional

from strands import ToolContext, tool

from services.order_service import CUSTOMER_EDITABLE_FIELDS, OrderService
from tools.ecommerce_tools import FlowControlTools, ToolBundle, _EcomToolBase
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
        self, order_id: str, reason: str, tool_context: ToolContext
    ) -> Any:
        """Cancel the user's own order. Call only after the user confirmed.
        Refused if the order is already shipped or closed.

        Args:
            order_id: Target order id.
            reason: The user's cancellation reason.
        """
        return self._run(tool_context, self.orders.cancel_order, order_id, reason)


def order_tools(logger_config) -> ToolBundle:
    ot = OrderAgentTools(logger_config)
    flow = FlowControlTools(logger_config)
    return ToolBundle(
        [ot, flow],
        [
            ot.get_my_orders,
            ot.get_order_details,
            ot.modify_order_by_customer,
            ot.cancel_order_by_customer,
            flow.complete_task,
            flow.fail_task,
        ],
    )
