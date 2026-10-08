import json
from typing import Any

from strands import Agent
from strands.agent.conversation_manager import SummarizingConversationManager
from strands.models import BedrockModel, CacheConfig

from configs.settings import settings
from tools.ecommerce_tools import cart_tools
from utils.common import CommonUtility
from utils.logger import Logger
from utils.wrapper import handle_errors, handle_errors_silent


class CartAgent:
    """
    Specialist agent for the shopper's cart and checkout.

    Cart: view, add, change quantity, remove. Checkout is a multi-step,
    confirm-before-execute flow: review cart -> choose delivery address -> delivery charges ->
    optional coupon -> payment method -> explicit total confirmation ->
    place order -> (online payments only) Razorpay create / verify / capture.

    Multi-turn. Sets ``status = "COMPLETE"`` with the order id when done, or
    ``"FAILED"`` on an unrecoverable backend error (via the flow tools).
    """

    sop_path = "chat/cart.sop.md"
    name = "CART"

    def __init__(self, logger_config):
        self.logger = Logger(__name__, logger_config)
        self.common_util = CommonUtility(logger_config)

        self.model = BedrockModel(
            model_id=settings.specialist_model_id,
            region_name=settings.region,
            temperature=0.0,
            cache_tools="default",
            cache_config=CacheConfig(strategy="anthropic"),
        )

        # longer window than other specialists: checkout carries running totals
        self.conversation_manager = SummarizingConversationManager(
            summary_ratio=0.3,
            preserve_recent_messages=12,
        )

        self._bundle = cart_tools(logger_config)
        self._flow_started = False

        self.agent = Agent(
            model=self.model,
            system_prompt=self.common_util.load_sop(self.sop_path),
            tools=self._bundle.tools,
            conversation_manager=self.conversation_manager,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Entry point: cart / checkout starts here
    # ─────────────────────────────────────────────────────────────────────────

    @handle_errors
    def run(self, user_input: str, state: dict | None = None) -> tuple:
        """
        Execute one turn of the cart / checkout conversation.

        Args:
            user_input: Raw (or orchestrator-enriched) user message this turn.
            state:      ``{"data": {...}}`` — shared session data. Contains
                        the auth state (token, user).

        Returns:
            (agent_response, {"data": updated_cart_data})
        """
        state = state or {}
        cart_data = state.get("data") if isinstance(state.get("data"), dict) else {}

        self.logger.info("[CartAgent] Turn started")
        self.agent.state.set("data", cart_data)

        if not self._flow_started:
            self._flow_started = True
            agent_input = self._build_first_turn_input(cart_data, user_input)
        else:
            agent_input = user_input

        response = self.agent(agent_input)

        updated_data = self.agent.state.get("data") or {}

        if updated_data.get("status") in ("COMPLETE", "FAILED"):
            self.logger.info(
                f"[CartAgent] Terminal status: {updated_data.get('status')}"
            )

        return response, {"data": updated_data}

    def reply_text(self, response: Any) -> str:
        return self.common_util.extract_text(response, self.agent.messages)

    # ─────────────────────────────────────────────────────────────────────────
    # Private helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _build_first_turn_input(self, cart_data: dict, user_input: str) -> str:
        """
        Build the enriched first-turn message for the LLM.
        Includes the signed-in user's name so the flow can address them.
        """
        user = cart_data.get("auth_state", {}).get("user") or {}
        cart_context = {"name": user.get("name") or user.get("fullName")}

        return f"{json.dumps(cart_context)}\n{user_input}"

    # ─────────────────────────────────────────────────────────────────────────
    # Reset
    # ─────────────────────────────────────────────────────────────────────────

    @handle_errors_silent
    def reset(self) -> None:
        """
        Clear conversation history and agent state.
        Called by orchestrator after task COMPLETE or on intent switch.
        """
        self.agent.messages = []
        self.agent.state.set("data", {})
        self._flow_started = False
        self.logger.info("[CartAgent] Reset complete — messages and state cleared")
