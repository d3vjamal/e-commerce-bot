"""OrderAgent — list orders, track an order, and cancel an order.

Cancellation is transactional: the agent confirms the specific order and a
reason with the user before calling ``ecom_cancel_order_by_customer``.
"""

from agents.base import SpecialistAgent
from tools.ecommerce_tools import order_tools


class OrderAgent(SpecialistAgent):
    sop_path = "chat/order.sop.md"
    name = "ORDER"

    def __init__(self, logger_config):
        super().__init__(logger_config, order_tools(logger_config))
