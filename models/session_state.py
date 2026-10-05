from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from models.session_context import SessionContext


class AuthState(BaseModel):
    """``data["auth_state"]`` — written by the orchestrator (host token) or ``ecom_login``."""

    token: Optional[str] = None
    user: Optional[Dict[str, Any]] = None
    verification_status: Optional[Literal["PASS", "FAIL"]] = None
    source: Optional[str] = None

    model_config = {"extra": "allow"}


class SessionData(BaseModel):
    """Shape of the orchestrator's ``agent.state["data"]``.

    Per-specialist ``*_state`` dicts stay loose; the SOPs own their contents.
    """

    session_context: Optional[SessionContext] = Field(
        default=None, alias="sessionContext"
    )
    auth_state: Optional[AuthState] = None

    intent: Optional[List[str]] = None
    pending_intents: List[str] = Field(default_factory=list)
    active_agent: Optional[str] = None
    status: Optional[Literal["COMPLETE", "FAILED", "ERROR"]] = None
    task_summary: Optional[str] = None
    order_id: Optional[str] = None

    browse_state: Dict[str, Any] = Field(default_factory=dict)
    cart_state: Dict[str, Any] = Field(default_factory=dict)
    checkout_state: Dict[str, Any] = Field(default_factory=dict)
    order_state: Dict[str, Any] = Field(default_factory=dict)
    account_state: Dict[str, Any] = Field(default_factory=dict)

    model_config = {"populate_by_name": True, "extra": "allow"}
