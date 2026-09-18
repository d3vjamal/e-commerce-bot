"""AccountAgent — delivery addresses, wishlists, and profile fields."""

from agents.base import SpecialistAgent
from tools.ecommerce_tools import account_tools


class AccountAgent(SpecialistAgent):
    sop_path = "chat/account.sop.md"
    name = "ACCOUNT"

    def __init__(self, logger_config):
        super().__init__(logger_config, account_tools(logger_config))
