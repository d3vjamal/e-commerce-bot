import json
from typing import Any, Dict, Optional
from urllib.parse import urljoin

import requests

from configs.settings import settings
from utils.logger import Logger
from utils.performance_timer import PerformanceTimer
from utils.retry import retry_api_call
from utils.wrapper import handle_errors


class EcommerceService:
    """
    Thin REST client for the e-commerce Express backend.

    - Supports every verb the API uses: GET / POST / PUT / PATCH / DELETE.
    - Builds requests against ``settings.ecommerce_api_base_url``.
    - Injects the caller's bearer token for authenticated routes.
    - Retries connection errors and 5xx responses (see ``retry_api_call``).
    - Returns the decoded JSON body, or a small dict describing the status
      when the response has no JSON payload.
    """

    def __init__(self, logger_config):
        self.logger = Logger(__name__, logger_config)
        self.base_url = (settings.ecommerce_api_base_url or "").rstrip("/")
        self.auth_scheme = (settings.ecommerce_auth_scheme or "").strip()
        self.token_header = (settings.ecommerce_token_header or "").strip()
        self.default_timeout = settings.ecommerce_api_timeout

    # ─────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────────────────────────────────────

    @retry_api_call
    def _send(
        self,
        method: str,
        url: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]],
        payload: Optional[Dict[str, Any]],
        timeout: int,
    ) -> requests.Response:
        response = requests.request(
            method=method,
            url=url,
            headers=headers,
            params=params,
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
        return response

    def _build_headers(
        self, token: Optional[str], extra: Optional[Dict[str, str]]
    ) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = (
                f"{self.auth_scheme} {token}" if self.auth_scheme else token
            )
            if self.token_header:
                headers[self.token_header] = token
        if extra:
            headers.update(extra)
        return headers

    @staticmethod
    def _mask(headers: Dict[str, str]) -> Dict[str, str]:
        masked = dict(headers)
        for key in ("Authorization", "token"):
            if masked.get(key):
                masked[key] = masked[key][:14] + "***"
        return masked

    # ─────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────

    @handle_errors
    def request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        payload: Optional[Dict[str, Any]] = None,
        token: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[int] = None,
    ) -> Any:
        if not self.base_url:
            raise ValueError(
                "ECOMMERCE_API_BASE_URL is not configured — set it in .env"
            )

        method = method.upper()
        url = urljoin(self.base_url + "/", path.lstrip("/"))
        request_headers = self._build_headers(token, headers)
        request_timeout = timeout or self.default_timeout

        with PerformanceTimer(self.logger, f"{method} {url}"):
            self.logger.debug(
                f"{method} {url} | params={params} | headers={self._mask(request_headers)}"
            )
            self.logger.debug(f"payload={json.dumps(payload, default=str)}")

            response = self._send(
                method, url, request_headers, params, payload, request_timeout
            )

            self.logger.info(f"{method} {url} -> {response.status_code}")
            self.logger.debug(f"response={response.text[:2000]}")

        if not response.content:
            return {"statusCode": response.status_code}
        try:
            return response.json()
        except ValueError:
            return {"statusCode": response.status_code, "raw": response.text}

    # Verb shortcuts -------------------------------------------------------

    def get(self, path: str, **kwargs) -> Any:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs) -> Any:
        return self.request("POST", path, **kwargs)

    def put(self, path: str, **kwargs) -> Any:
        return self.request("PUT", path, **kwargs)

    def patch(self, path: str, **kwargs) -> Any:
        return self.request("PATCH", path, **kwargs)

    def delete(self, path: str, **kwargs) -> Any:
        return self.request("DELETE", path, **kwargs)
