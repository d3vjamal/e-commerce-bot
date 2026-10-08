import json
from typing import Any

from strands import Agent
from strands.agent.conversation_manager import SummarizingConversationManager

from agents.base import build_specialist_model
from tools.ecommerce_tools import account_tools
from utils.common import CommonUtility
from utils.logger import Logger
from utils.wrapper import handle_errors, handle_errors_silent


class AccountAgent:
    """
    Specialist agent for the shopper's account: delivery addresses,
    wishlists and profile fields (name / mobile number).
    Multi-turn: reads current state, confirms changes with the user, then
    executes via the account tools. Email / password changes are out of scope.
    """

    sop_path = "chat/account.sop.md"
    name = "ACCOUNT"

    def __init__(self, logger_config):
        self.logger = Logger(__name__, logger_config)
        self.common_util = CommonUtility(logger_config)

        self.model = build_specialist_model()

        self.conversation_manager = SummarizingConversationManager(
            summary_ratio=0.3,
            preserve_recent_messages=10,
        )

        self._bundle = account_tools(logger_config)
        self._flow_started = False

        self.agent = Agent(
            model=self.model,
            system_prompt=self.common_util.load_sop(self.sop_path),
            tools=self._bundle.tools,
            conversation_manager=self.conversation_manager,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Entry point: account conversation starts here
    # ─────────────────────────────────────────────────────────────────────────

    @handle_errors
    def run(self, user_input: str, state: dict | None = None) -> tuple:
        """
        Execute one turn of the account conversation.

        Args:
            user_input: Raw (or orchestrator-enriched) user message this turn.
            state:      ``{"data": {...}}`` — shared session data. Contains
                        the auth state (token, user).

        Returns:
            (agent_response, {"data": updated_account_data})
        """
        state = state or {}
        account_data = state.get("data") if isinstance(state.get("data"), dict) else {}

        self.logger.info("[AccountAgent] Turn started")
        self.agent.state.set("data", account_data)

        if not self._flow_started:
            self._flow_started = True
            agent_input = self._build_first_turn_input(account_data, user_input)
        else:
            agent_input = user_input

        response = self.agent(agent_input)

        updated_data = self.agent.state.get("data") or {}

        if updated_data.get("status") in ("COMPLETE", "FAILED"):
            self.logger.info(
                f"[AccountAgent] Terminal status: {updated_data.get('status')}"
            )

        return response, {"data": updated_data}

    def reply_text(self, response: Any) -> str:
        return self.common_util.extract_text(response, self.agent.messages)

    # ─────────────────────────────────────────────────────────────────────────
    # Private helpers
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _signed_in_user(account_data: dict) -> dict:
        return account_data.get("auth_state", {}).get("user") or {}

    def _build_first_turn_input(self, account_data: dict, user_input: str) -> str:
        """
        Build the enriched first-turn message for the LLM.
        Includes the signed-in user's id, name and phone.
        """
        user = self._signed_in_user(account_data)
        account_context = {
            "user_id": user.get("_id") or user.get("id"),
            "name": user.get("name") or user.get("fullName"),
            "phone": user.get("phone") or user.get("mobile"),
        }

        return f"{json.dumps(account_context)}\n{user_input}"

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
        self.logger.info("[AccountAgent] Reset complete — messages and state cleared")
