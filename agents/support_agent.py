from typing import Any

from strands import Agent
from strands.agent.conversation_manager import SummarizingConversationManager

from agents.base import build_specialist_model
from tools.support_tools import support_tools
from utils.common import CommonUtility
from utils.logger import Logger
from utils.wrapper import handle_errors, handle_errors_silent


class SupportAgent:
    """
    Specialist agent for FAQ, store policies, and Terms & Conditions.

    Public and read-only. Answers from the store's website policy pages and
    the Bedrock knowledge base (falling back to ``sops/faq.md``); never from
    the model's own knowledge. Stateless per question — the orchestrator
    resets it after every turn.
    """

    sop_path = "chat/support.sop.md"
    name = "SUPPORT"

    def __init__(self, logger_config):
        self.logger = Logger(__name__, logger_config)
        self.common_util = CommonUtility(logger_config)

        self.model = build_specialist_model()

        self.conversation_manager = SummarizingConversationManager(
            summary_ratio=0.3,
            preserve_recent_messages=10,
        )

        self._bundle = support_tools(logger_config)

        self.agent = Agent(
            model=self.model,
            system_prompt=self.common_util.load_sop(self.sop_path),
            tools=self._bundle.tools,
            conversation_manager=self.conversation_manager,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Entry point: a support question starts here
    # ─────────────────────────────────────────────────────────────────────────

    @handle_errors
    def run(self, user_input: str, state: dict | None = None) -> tuple:
        """
        Answer one support question.

        Args:
            user_input: The shopper's question.
            state:      ``{"data": {...}}`` — unused beyond being handed to
                        the tools; support needs no sign-in.

        Returns:
            (agent_response, {"data": updated_data})
        """
        state = state or {}
        support_data = state.get("data") if isinstance(state.get("data"), dict) else {}

        self.logger.info("[SupportAgent] Turn started")
        self.agent.state.set("data", support_data)

        response = self.agent(user_input)

        return response, {"data": self.agent.state.get("data") or {}}

    def reply_text(self, response: Any) -> str:
        return self.common_util.extract_text(response, self.agent.messages)

    # ─────────────────────────────────────────────────────────────────────────
    # Reset
    # ─────────────────────────────────────────────────────────────────────────

    @handle_errors_silent
    def reset(self) -> None:
        """
        Clear conversation history and agent state.
        Called by orchestrator after every answered question.
        """
        self.agent.messages = []
        self.agent.state.set("data", {})
        self.logger.info("[SupportAgent] Reset complete — messages and state cleared")
