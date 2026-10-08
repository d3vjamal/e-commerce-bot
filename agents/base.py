"""Shared base class for the commerce specialist agents.

Every specialist owns an isolated Strands ``Agent`` with its own summarising
conversation manager and SOP. The orchestrator calls ``run()`` once per user
turn, passing the shared session ``data`` dict; the specialist returns its
reply plus the (mutated) ``data`` for the orchestrator to persist.
"""

from typing import Any, Optional

from strands import Agent
from strands.agent.conversation_manager import SummarizingConversationManager
from strands.models import BedrockModel, CacheConfig

from configs.settings import settings
from tools.ecommerce_tools import ToolBundle
from utils.common import CommonUtility
from utils.logger import Logger


def build_specialist_model(model_id: Optional[str] = None, temperature: float = 0.0):
    """Bedrock model for a specialist. Anthropic prompt caching is only enabled
    for Anthropic model ids (other models, e.g. Nova, reject it)."""
    resolved_model_id = model_id or settings.specialist_model_id
    cache_kwargs: dict[str, Any] = {}
    if "anthropic" in resolved_model_id:
        cache_kwargs = {
            "cache_tools": "default",
            "cache_config": CacheConfig(strategy="anthropic"),
        }
    return BedrockModel(
        model_id=resolved_model_id,
        region_name=settings.region,
        temperature=temperature,
        **cache_kwargs,
    )


class SpecialistAgent:
    """Base for auth / browse / cart / checkout / order / account agents."""

    #: overridden by subclasses — path under ``sops/`` for the system prompt
    sop_path: str = ""
    #: short label used in logs and as the ``active_agent`` marker
    name: str = "specialist"

    def __init__(
        self,
        logger_config,
        tool_bundle: ToolBundle,
        *,
        model_id: Optional[str] = None,
        temperature: float = 0.0,
        summary_ratio: float = 0.3,
        preserve_recent_messages: int = 10,
    ):
        self.logger = Logger(__name__, logger_config)
        self.common_util = CommonUtility(logger_config)
        self._bundle = tool_bundle

        self.model = build_specialist_model(model_id, temperature)

        self.conversation_manager = SummarizingConversationManager(
            summary_ratio=summary_ratio,
            preserve_recent_messages=preserve_recent_messages,
        )

        self.agent = Agent(
            model=self.model,
            system_prompt=self.common_util.load_sop(self.sop_path),
            tools=tool_bundle.tools,
            conversation_manager=self.conversation_manager,
        )

    # ─────────────────────────────────────────────────────────────────────
    # Entry point
    # ─────────────────────────────────────────────────────────────────────

    def run(self, user_input: str, state: dict) -> tuple[Any, dict]:
        """Run one turn.

        Args:
            user_input: message to feed the specialist this turn (the
                orchestrator may enrich the first-turn message with context).
            state: ``{"data": {...}}`` — the shared session data.

        Returns:
            ``(agent_response, {"data": <mutated data>})``
        """
        try:
            self.agent.state.set("data", state.get("data", {}) or {})
            response = self.agent(user_input)
            return response, {"data": self.agent.state.get("data") or {}}
        except Exception as exc:  # noqa: BLE001
            self.logger.exception(f"[{self.name}] run failure: {exc}")
            data = self.agent.state.get("data") or state.get("data", {}) or {}
            data["status"] = "ERROR"
            return f"System error in {self.name}. Please try again.", {"data": data}

    def reply_text(self, response: Any) -> str:
        return self.common_util.extract_text(response, self.agent.messages)

    def reset(self) -> None:
        self.agent.messages = []
        self.logger.info(f"[{self.name}] conversation history cleared")
