"""BrowseAgent — public product discovery, detail, and availability.

No authentication required. Uses the catalogue search / detail tools and
returns results for the orchestrator's LLM to present. Records the last
viewed product in ``browse_state.focused_product_id`` so a following
"add this to my cart" resolves without re-asking.
"""

from agents.base import SpecialistAgent
from tools.ecommerce_tools import browse_tools


class BrowseAgent(SpecialistAgent):
    sop_path = "chat/browse.sop.md"
    name = "BROWSE"

    def __init__(self, logger_config):
        super().__init__(logger_config, browse_tools(logger_config), temperature=0.2)
