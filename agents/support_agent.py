"""SupportAgent — FAQ, store policies, and Terms & Conditions.

Public and read-only. Answers from the store's website policy pages and the
Bedrock knowledge base (falling back to ``sops/faq.md``); never from the
model's own knowledge. Stateless per question — the orchestrator resets it
after every turn.
"""

from agents.base import SpecialistAgent
from tools.support_tools import support_tools


class SupportAgent(SpecialistAgent):
    sop_path = "chat/support.sop.md"
    name = "SUPPORT"

    def __init__(self, logger_config):
        super().__init__(logger_config, support_tools(logger_config), temperature=0.0)
