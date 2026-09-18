from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field


class SessionContext(BaseModel):
    """
    Per-conversation context supplied by the host app in the invocation
    payload under ``input.details``. Everything is optional so anonymous
    browsing still works.
    """

    channel: Literal["CHAT"] = "CHAT"
    role: Literal["customer", "admin", "delivery"] = "customer"
    locale: str = "en"

    # Identity of the signed-in user in the host app, if any.
    user_id: Optional[str] = Field(default=None, alias="userId")

    # Pre-issued backend JWT from the host app's own session. When present the
    # AuthAgent adopts it silently instead of running an interactive login.
    auth_token: Optional[str] = Field(default=None, alias="authToken")

    model_config = {"populate_by_name": True, "extra": "allow"}

    @classmethod
    def from_details(cls, details: Optional[Dict[str, Any]]) -> "SessionContext":
        """Build a context from the raw ``input.details`` dict, tolerating junk."""
        if not isinstance(details, dict):
            return cls()
        try:
            return cls.model_validate(details)
        except Exception:
            return cls()
