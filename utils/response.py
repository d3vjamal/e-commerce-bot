"""Generic response envelope for REST calls.

Every API call can be normalised to one shape, so callers (tools, services)
never branch on raw ``requests`` objects or exception types::

    {"success": bool, "status_code": int | None, "data": Any,
     "message": str | None, "error": str | None}

``ResponseBuilder`` does the conversion. It logs through the project
``Logger`` and is protected by the ``wrapper.py`` error decorators, so a
malformed response can never raise out of the builder.
"""

from typing import Any, Optional

import requests
from pydantic import BaseModel, ConfigDict

from utils.logger import Logger
from utils.wrapper import handle_errors_with_fallback


class ApiResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    success: bool
    status_code: Optional[int] = None
    data: Any = None
    message: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(exclude_none=True)


_BUILD_FAILED = ApiResponse(
    success=False, error="response_build_failed", message="Could not process the response."
)


class ResponseBuilder:
    def __init__(self, logger_config):
        # ``handle_errors_*`` decorators log through ``self.logger``
        self.logger = Logger(__name__, logger_config)

    def ok(
        self, data: Any = None, *, status_code: int = 200, message: Optional[str] = None
    ) -> ApiResponse:
        return ApiResponse(
            success=True, status_code=status_code, data=data, message=message
        )

    def fail(
        self,
        error: str,
        *,
        message: Optional[str] = None,
        status_code: Optional[int] = None,
        data: Any = None,
    ) -> ApiResponse:
        self.logger.warning(f"API failure | status={status_code} | error={error}")
        return ApiResponse(
            success=False,
            status_code=status_code,
            error=error,
            message=message,
            data=data,
        )

    @handle_errors_with_fallback(_BUILD_FAILED)
    def from_response(self, response: requests.Response) -> ApiResponse:
        """Wrap a ``requests`` response. 2xx → success, anything else → failure
        carrying the backend's message when its body has one."""
        try:
            body = response.json() if response.content else None
        except ValueError:
            body = {"raw": response.text[:2000]}

        if response.ok:
            return self.ok(body, status_code=response.status_code)

        message = None
        if isinstance(body, dict):
            message = body.get("message") or body.get("error")
        return self.fail(
            f"http_{response.status_code}",
            message=str(message) if message else response.reason,
            status_code=response.status_code,
            data=body,
        )

    @handle_errors_with_fallback(_BUILD_FAILED)
    def from_exception(self, exc: Exception) -> ApiResponse:
        """Wrap an exception raised by a call. ``HTTPError`` keeps its response."""
        response = getattr(exc, "response", None)
        if isinstance(exc, requests.HTTPError) and response is not None:
            return self.from_response(response)
        if isinstance(exc, requests.Timeout):
            return self.fail("timeout", message="The request timed out.")
        if isinstance(exc, requests.ConnectionError):
            return self.fail("connection_error", message="Could not reach the server.")
        return self.fail("request_failed", message=str(exc))
