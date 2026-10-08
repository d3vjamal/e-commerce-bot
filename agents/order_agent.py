import json
from typing import Any

from strands import Agent
from strands.agent.conversation_manager import SummarizingConversationManager

from agents.base import build_specialist_model
from tools.order_tools import order_tools
from utils.common import CommonUtility
from utils.logger import Logger
from utils.wrapper import handle_errors, handle_errors_silent


class OrderAgent:
    """
    Specialist agent for orders: place, list/track, modify (delivery details
    or item quantity) and cancel.
    Multi-turn: collects details, confirms with the user, then executes via
    the order tools (agent → tools/order_tools.py → services/order_service.py).
    """

    sop_path = "chat/order.sop.md"
    name = "ORDER"

    def __init__(self, logger_config):
        self.logger = Logger(__name__, logger_config)
        self.common_util = CommonUtility(logger_config)

        self.model = build_specialist_model()

        self.conversation_manager = SummarizingConversationManager(
            summary_ratio=0.3,
            preserve_recent_messages=10,
        )

        self._bundle = order_tools(logger_config)
        self._flow_started = False

        self.agent = Agent(
            model=self.model,
            system_prompt=self.common_util.load_sop(self.sop_path),
            tools=self._bundle.tools,
            conversation_manager=self.conversation_manager,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Entry point: order conversation starts here
    # ─────────────────────────────────────────────────────────────────────────

    @handle_errors
    def run(self, user_input: str, state: dict | None = None) -> tuple:
        """
        Execute one turn of the order conversation.

        Args:
            user_input: Raw (or orchestrator-enriched) user message this turn.
            state:      ``{"data": {...}}`` — shared session data. Contains
                        the auth state (token) and any previous order_id.

        Returns:
            (agent_response, {"data": updated_order_data})
        """
        state = state or {}
        order_data = state.get("data") if isinstance(state.get("data"), dict) else {}

        self.logger.info("[OrderAgent] Turn started")
        self.agent.state.set("data", order_data)

        if not self._flow_started:
            self._flow_started = True
            agent_input = self._build_first_turn_input(order_data, user_input)
        else:
            agent_input = user_input

        response = self.agent(agent_input)

        updated_data = self.agent.state.get("data") or {}

        if updated_data.get("status") in ("COMPLETE", "FAILED"):
            self.logger.info(
                f"[OrderAgent] Terminal status: {updated_data.get('status')}"
            )

        return response, {"data": updated_data}

    def reply_text(self, response: Any) -> str:
        return self.common_util.extract_text(response, self.agent.messages)

    # ─────────────────────────────────────────────────────────────────────────
    # Private helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _build_first_turn_input(self, order_data: dict, user_input: str) -> str:
        """
        Build the enriched first-turn message for the LLM.
        Includes the last known order id so "my order" can be resolved.
        """
        order_context = {"last_order_id": order_data.get("order_id")}

        return f"{json.dumps(order_context)}\n{user_input}"

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
        self.logger.info("[OrderAgent] Reset complete — messages and state cleared")
