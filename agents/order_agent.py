"""OrderAgent — list, track, modify delivery details of, and cancel orders.

Flow: agent → ``tools/order_tools.py`` → ``services/order_service.py`` →
REST. Modify and cancel are transactional: the agent confirms the specific
order (and, for cancel, a reason) with the user before calling the tool.
"""

from agents.base import SpecialistAgent
from tools.order_tools import order_tools


class OrderAgent(SpecialistAgent):
    sop_path = "chat/order.sop.md"
    name = "ORDER"

    def __init__(self, logger_config):
        super().__init__(logger_config, order_tools(logger_config))
