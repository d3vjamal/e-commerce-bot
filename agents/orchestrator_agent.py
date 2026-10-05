"""Commerce Orchestrator.

Design principle (unchanged from the original architecture): the LLM owns all
routing and sequencing decisions, guided by the SOP system prompt. The Python
``@tool`` handlers here are thin — they run a specialist sub-agent for one turn,
persist its nested state, enforce the auth gate, and return a structured result.
No routing branches live in Python.
"""

import json
from typing import Any, List

from strands import Agent, ToolContext, tool
from strands.agent.conversation_manager import SummarizingConversationManager
from strands.models import BedrockModel, CacheConfig

from agents.account_agent import AccountAgent
from agents.auth_agent import AuthAgent
from agents.browse_agent import BrowseAgent
from agents.cart_agent import CartAgent
from agents.checkout_agent import CheckoutAgent
from agents.order_agent import OrderAgent
from agents.support_agent import SupportAgent
from configs.settings import settings
from models.session_context import SessionContext
from utils.common import CommonUtility
from utils.logger import Logger

# intent -> specialist handler name, and whether a signed-in user is required
INTENT_SPEC = {
    "BROWSE": ("handle_browse", False),
    "PRODUCT_DETAIL": ("handle_browse", False),
    "CART": ("handle_cart", True),
    "CHECKOUT": ("handle_checkout", True),
    "ORDER_TRACK": ("handle_order", True),
    "ORDER_CANCEL": ("handle_order", True),
    "ACCOUNT": ("handle_account", True),
    "SUPPORT": ("handle_support", False),
    "UNKNOWN": ("handle_fallback", False),
}
VALID_INTENTS = set(INTENT_SPEC)
AUTH_INTENTS = {i for i, (_, needs) in INTENT_SPEC.items() if needs}

# nested-state keys cleared when a flow finishes or the user switches tasks
_FLOW_KEYS = (
    "intent",
    "pending_intents",
    "active_agent",
    "status",
    "task_summary",
    "order_id",
    "browse_state",
    "cart_state",
    "checkout_state",
    "order_state",
    "account_state",
)


class OrchestratorAgent:
    def __init__(self, logger_config, session_id=None):
        self.logger = Logger(__name__, logger_config)
        self.common_util = CommonUtility(logger_config)
        self.session_id = session_id

        cache_kwargs: dict[str, Any] = {}
        if "anthropic" in settings.orchestrator_model_id:
            cache_kwargs = {
                "cache_tools": "default",
                "cache_config": CacheConfig(strategy="auto"),
            }

        self.model = BedrockModel(
            model_id=settings.orchestrator_model_id,
            region_name=settings.region,
            temperature=0.0,
            **cache_kwargs,
            guardrail_id=settings.guardrail_id,
            guardrail_version=settings.guardrail_version,
        )

        self.conversation_manager = SummarizingConversationManager(
            summary_ratio=0.8,
            preserve_recent_messages=6,
        )

        # specialist sub-agents (each owns an isolated conversation)
        self.auth_agent = AuthAgent(logger_config)
        self.browse_agent = BrowseAgent(logger_config)
        self.cart_agent = CartAgent(logger_config)
        self.checkout_agent = CheckoutAgent(logger_config)
        self.order_agent = OrderAgent(logger_config)
        self.account_agent = AccountAgent(logger_config)

        self.support_agent = SupportAgent(logger_config)

        self.agent = Agent(
            model=self.model,
            system_prompt=self.common_util.load_sop("chat/orchestrator.sop.md"),
            tools=[
                self.route_intent,
                self.handle_auth,
                self.handle_browse,
                self.handle_cart,
                self.handle_checkout,
                self.handle_order,
                self.handle_account,
                self.handle_support,
                self.handle_fallback,
            ],
            conversation_manager=self.conversation_manager,
        )

    # ─────────────────────────────────────────────────────────────────────
    # Entry point
    # ─────────────────────────────────────────────────────────────────────

    def run(self, user_input: str, details: dict) -> tuple[Any, dict]:
        try:
            ctx = SessionContext.from_details(details)
            self.logger.info(
                f"Orchestrator START | role={ctx.role} | user={ctx.user_id} "
                f"| token_supplied={bool(ctx.auth_token)}"
            )

            data = self.agent.state.get("data") or {}
            if not data:
                # auth_token lives only in auth_state below — sessionContext is
                # never re-read for it, so don't duplicate the raw JWT here.
                data = {
                    "sessionContext": ctx.model_dump(
                        by_alias=True, exclude={"auth_token"}
                    )
                }
                if ctx.auth_token:
                    data["auth_state"] = {
                        "token": ctx.auth_token,
                        "user": {"id": ctx.user_id} if ctx.user_id else None,
                        "verification_status": "PASS",
                        "source": "host_app",
                    }
                self.agent.state.set("data", data)
                self.logger.info("New session — state initialised")
            else:
                self.logger.info(
                    f"Existing session | turn={data.get('turn_count', 0)} "
                    f"| active_agent={data.get('active_agent')}"
                )

            result = self.agent(user_input)
            data = self.agent.state.get("data") or {}
            self.logger.info(
                f"Orchestrator END | active_agent={data.get('active_agent')} "
                f"| intent={data.get('intent')} | turn={data.get('turn_count')}"
            )
            return self.common_util.extract_text(result, self.agent.messages), data
        except Exception as exc:  # noqa: BLE001
            self.logger.exception(f"[Orchestrator] run failure: {exc}")
            return "Sorry, something went wrong. Please try again.", {}

    # ─────────────────────────────────────────────────────────────────────
    # Tool: IntentRouter
    # ─────────────────────────────────────────────────────────────────────

    @tool(context=True, name="IntentRouter")
    def route_intent(self, intent: List[str], tool_context: ToolContext) -> str:
        """Sanitise and store the LLM-classified intent(s), bump the turn count,
        and return a routing signal.

        Args:
            intent: classified intents, e.g. ["BROWSE"] or ["CART", "CHECKOUT"].

        Returns:
            JSON with validated_intents, turn_count, active_agent, auth_status,
            auth_required, pending_intents, role.
        """
        try:
            state = tool_context.agent.state
            data = state.get("data") or {}

            if not isinstance(intent, list):
                intent = [intent]
            validated = [
                i.upper() for i in intent if (i or "").upper() in VALID_INTENTS
            ]
            if not validated:
                validated = ["UNKNOWN"]

            data["intent"] = validated
            data["pending_intents"] = validated
            data["turn_count"] = data.get("turn_count", 0) + 1
            state.set("data", data)

            auth_status = (data.get("auth_state") or {}).get("verification_status")
            self.logger.info(
                f"[IntentRouter] turn={data['turn_count']} intent={validated} "
                f"auth={auth_status} active_agent={data.get('active_agent')}"
            )
            return json.dumps(
                {
                    "validated_intents": validated,
                    "turn_count": data["turn_count"],
                    "active_agent": data.get("active_agent"),
                    "auth_status": auth_status,
                    "auth_required": bool(set(validated) & AUTH_INTENTS),
                    "pending_intents": data.get("pending_intents", []),
                    "role": (data.get("sessionContext") or {}).get("role", "customer"),
                }
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.exception(f"[IntentRouter] {exc}")
            return json.dumps({"validated_intents": ["UNKNOWN"], "error": str(exc)})

    # ─────────────────────────────────────────────────────────────────────
    # Tool: Auth
    # ─────────────────────────────────────────────────────────────────────

    @tool(context=True, name="Auth")
    def handle_auth(self, user_input: str, tool_context: ToolContext) -> str:
        """Bring the user to an authenticated state. Call when auth_status is not
        "PASS" and an auth-required intent is pending.

        On PASS: returns auth_status="PASS" — proceed to the specialist tool.
        On PENDING: returns next_question — present it and call Auth again next turn.
        """
        try:
            state = tool_context.agent.state
            data = state.get("data") or {}

            if (data.get("auth_state") or {}).get("verification_status") == "PASS":
                return json.dumps({"auth_status": "PASS"})

            response, updated = self.auth_agent.run(user_input, {"data": data})
            new_data = updated["data"]
            new_data["active_agent"] = "AUTH"
            state.set("data", new_data)

            status = (new_data.get("auth_state") or {}).get(
                "verification_status", "PENDING"
            )
            if status == "PASS":
                new_data["active_agent"] = None
                state.set("data", new_data)
                return json.dumps(
                    {"auth_status": "PASS", "message": "You're signed in."}
                )
            return json.dumps(
                {
                    "auth_status": status,
                    "next_question": self.auth_agent.reply_text(response),
                }
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.exception(f"[Auth] {exc}")
            return json.dumps({"auth_status": "ERROR", "message": "Sign-in failed."})

    # ─────────────────────────────────────────────────────────────────────
    # Specialist runners
    # ─────────────────────────────────────────────────────────────────────

    def _run_specialist(
        self,
        agent,
        label: str,
        state_key: str,
        user_input: str,
        tool_context: ToolContext,
        *,
        needs_auth: bool,
        first_turn_prefix: str = "",
    ) -> str:
        state = tool_context.agent.state
        data = state.get("data") or {}

        if needs_auth and (data.get("auth_state") or {}).get(
            "verification_status"
        ) != "PASS":
            return json.dumps(
                {
                    "status": "AUTH_REQUIRED",
                    "message": "The user must sign in before this action.",
                }
            )

        flow = data.get(state_key) or {}
        first_turn = not flow.get("flow_started")
        agent_input = user_input
        if first_turn:
            flow["flow_started"] = True
            data[state_key] = flow
            state.set("data", data)
            if first_turn_prefix:
                agent_input = f"{first_turn_prefix}\n\n{user_input}"

        response, updated = agent.run(agent_input, {"data": data})
        new_data = updated["data"]
        new_data["active_agent"] = label
        state.set("data", new_data)

        status = new_data.get("status")
        text = agent.reply_text(response)

        if status in ("COMPLETE", "FAILED"):
            summary = new_data.get("task_summary") or text
            order_id = new_data.get("order_id")
            self._reset_flow_state(state)
            return json.dumps(
                {"status": status, "message": summary, "order_id": order_id}
            )

        return json.dumps({"status": "IN_PROGRESS", "response": text})

    @tool(context=True, name="BrowseCatalogue")
    def handle_browse(self, user_input: str, tool_context: ToolContext) -> str:
        """Product discovery, product detail, and delivery availability. Public —
        no sign-in needed. Returns catalogue results for you to present."""
        return self._run_specialist(
            self.browse_agent,
            "BROWSE",
            "browse_state",
            user_input,
            tool_context,
            needs_auth=False,
        )

    @tool(context=True, name="ManageCart")
    def handle_cart(self, user_input: str, tool_context: ToolContext) -> str:
        """View or change the signed-in shopper's cart (add / update qty / remove)."""
        return self._run_specialist(
            self.cart_agent,
            "CART",
            "cart_state",
            user_input,
            tool_context,
            needs_auth=True,
        )

    @tool(context=True, name="Checkout")
    def handle_checkout(self, user_input: str, tool_context: ToolContext) -> str:
        """Run the checkout flow: address, delivery charge, coupon, payment,
        confirmation, place order. Multi-turn; ends COMPLETE with an order id."""
        return self._run_specialist(
            self.checkout_agent,
            "CHECKOUT",
            "checkout_state",
            user_input,
            tool_context,
            needs_auth=True,
            first_turn_prefix="Begin checkout. Review the cart first.",
        )

    @tool(context=True, name="ManageOrders")
    def handle_order(self, user_input: str, tool_context: ToolContext) -> str:
        """List orders, track an order, or cancel an order (with confirmation)."""
        return self._run_specialist(
            self.order_agent,
            "ORDER",
            "order_state",
            user_input,
            tool_context,
            needs_auth=True,
        )

    @tool(context=True, name="ManageAccount")
    def handle_account(self, user_input: str, tool_context: ToolContext) -> str:
        """Delivery addresses, wishlists, and profile fields for the signed-in user."""
        return self._run_specialist(
            self.account_agent,
            "ACCOUNT",
            "account_state",
            user_input,
            tool_context,
            needs_auth=True,
        )

    @tool(context=True, name="Support")
    def handle_support(self, user_input: str, tool_context: ToolContext) -> str:
        """Answer FAQ, store-policy and terms & conditions questions (returns,
        delivery, payments, privacy, terms). Reads the website policy pages and
        knowledge base. Returns a sourced answer — relay it, do not add policy."""
        _ = tool_context
        try:
            response, _state = self.support_agent.run(user_input, {"data": {}})
            text = self.support_agent.reply_text(response)
            return json.dumps({"status": "OK", "response": text})
        finally:
            # one-shot Q&A: don't let stale answers leak into the next question
            self.support_agent.reset()

    @tool(context=True, name="Fallback")
    def handle_fallback(self, user_input: str, tool_context: ToolContext) -> str:
        """Out-of-scope, unsupported-language, or unrecognised requests."""
        self.logger.info(f"[Fallback] invoked | q={user_input[:80]!r}")
        _ = tool_context
        return json.dumps(
            {
                "status": "OK",
                "message": (
                    f"I can help with shopping on {settings.brand_name} — finding "
                    "products, your cart, checkout, orders, and your account. "
                    "Could you rephrase your request?"
                ),
            }
        )

    # ─────────────────────────────────────────────────────────────────────
    # State reset
    # ─────────────────────────────────────────────────────────────────────

    def _reset_flow_state(self, state) -> None:
        """Clear per-flow keys after a task completes / the user switches tasks.
        Preserves sessionContext, auth_state, and turn_count."""
        try:
            data = state.get("data") or {}
            for key in _FLOW_KEYS:
                data.pop(key, None)
            state.set("data", data)
            for agent in (
                self.browse_agent,
                self.cart_agent,
                self.checkout_agent,
                self.order_agent,
                self.account_agent,
            ):
                agent.reset()
            self.logger.info("[State] flow keys cleared (auth_state preserved)")
        except Exception as exc:  # noqa: BLE001
            self.logger.exception(f"[State] reset failure: {exc}")
