"""CartAgent — view and mutate the signed-in shopper's cart."""

from agents.base import SpecialistAgent
from tools.ecommerce_tools import cart_tools


class CartAgent(SpecialistAgent):
    sop_path = "chat/cart.sop.md"
    name = "CART"

    def __init__(self, logger_config):
        super().__init__(logger_config, cart_tools(logger_config))
