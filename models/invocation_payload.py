from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from models.session_context import SessionContext


class InvocationInput(BaseModel):
    """Typed shape of ``InvocationRequest.input``."""

    prompt: str
    details: Optional[SessionContext] = None


class InvocationOutput(BaseModel):
    """Typed shape of ``InvocationResponse.output``."""

    message: Any
    timestamp: str
    session_id: Optional[str] = Field(default=None, alias="sessionId")
    session_data: Dict[str, Any] = Field(default_factory=dict, alias="sessionData")
    time_taken: str = Field(alias="timeTaken")

    model_config = {"populate_by_name": True}
