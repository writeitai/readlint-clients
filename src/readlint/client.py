"""HTTPS transport adapted from mountable's Python SDK; see docs/development.md."""

from __future__ import annotations

import os
import re
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, Self, cast
from urllib.parse import urlsplit
from uuid import UUID

import httpx

from readlint.types import Evaluation, EvaluationPage

DEFAULT_BASE_URL = "https://readlint.com"

_RECOVERY = {
    "authentication_required": "Run `readlint login` or set a valid READLINT_API_KEY.",
    "evaluation_credit_exhausted": "Check your evaluation credit in the web app.",
    "evaluation_not_allowed": "Ask support@readlint.com for evaluation access.",
    "evaluation_disabled": "Try again later with the same idempotency key and article.",
    "evaluation_context_exceeded": "Shorten the article and submit with a new key.",
    "evaluation_not_found": "List evaluations to find an unexpired evaluation ID.",
    "idempotency_key_reused": "Use the original article and options, or a new key for a new evaluation.",
    "validation_error": "Check the input and command help before retrying.",
    "invalid_page_size": "Choose a smaller --limit.",
    "authorization_pending": "Approve the code in the web app.",
    "slow_down": "Wait longer before polling again.",
    "access_denied": "Approval was denied, used, or canceled; run `readlint login` again.",
    "expired_token": "The code expired; run `readlint login` again.",
    "invalid_grant": "The device request is invalid; run `readlint login` again.",
    "unsupported_grant_type": "Update the readlint package and try login again.",
}


class ReadlintError(Exception):
    """A sanitized error. status is None when no HTTP answer arrived."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status: int | None = None,
        evaluation_id: str | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.status = status
        self.evaluation_id = evaluation_id
        super().__init__(message)

    def as_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": self.message,
            "status": self.status,
            "evaluation_id": self.evaluation_id,
        }


def normalize_base_url(value: str) -> str:
    parts = urlsplit(value)
    try:
        _ = parts.port
    except ValueError:
        raise ValueError("Use a valid HTTPS origin and port.") from None
    if (
        parts.scheme not in {"http", "https"}
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
        or parts.path not in {"", "/"}
        or (
            parts.scheme == "http"
            and parts.hostname not in {"localhost", "127.0.0.1", "::1"}
        )
    ):
        raise ValueError(
            "Use an HTTPS origin for --base-url (HTTP is allowed on loopback)."
        )
    return value.rstrip("/")


def _problem(response: httpx.Response) -> ReadlintError:
    try:
        body = response.json()
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        body = {}
    detail = body.get("detail")
    code = detail.get("code") if isinstance(detail, dict) else body.get("error")
    # Never echo arbitrary server text, tokens, validation input, or HTML.
    if not isinstance(code, str) or code not in _RECOVERY:
        code = {
            401: "authentication_required",
            422: "validation_error",
            429: "rate_limited",
        }.get(response.status_code, "api_error")
    recovery = _RECOVERY.get(
        code, "Retry later; for a submission reuse its key and identical input."
    )
    return ReadlintError(
        code,
        f"HTTP {response.status_code}: {code}. {recovery}",
        status=response.status_code,
    )


def _retry_delay(response: httpx.Response | None, attempt: int) -> float | None:
    delay = float(2**attempt)
    if response is not None and (value := response.headers.get("Retry-After")):
        try:
            delay = float(value)
        except ValueError:
            try:
                delay = (
                    parsedate_to_datetime(value) - datetime.now(UTC)
                ).total_seconds()
            except (ValueError, TypeError, OverflowError):
                return delay
    # Do not retry early when the server asks for a long wait.
    return max(0, delay) if delay <= 60 else None


class Readlint:
    """Synchronous SDK. Retries reads and idempotent evaluation submissions twice.

    Pass a key explicitly or set READLINT_API_KEY. Use as a context manager to
    close the connection pool. Responses are typed JSON dictionaries.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        timeout: float = 120,
        max_retries: int = 2,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = normalize_base_url(
            base_url or os.environ.get("READLINT_BASE_URL") or DEFAULT_BASE_URL
        )
        self._api_key = api_key or os.environ.get("READLINT_API_KEY")
        if max_retries < 0 or timeout <= 0:
            raise ValueError(
                "max_retries must be nonnegative and timeout must be positive."
            )
        self.max_retries = max_retries
        self._http = httpx.Client(
            timeout=timeout, transport=transport, follow_redirects=False
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def _request(
        self,
        method: str,
        path: str,
        *,
        authenticated: bool = True,
        retry: bool = False,
        **kwargs: Any,
    ) -> Any:
        headers = kwargs.pop("headers", {})
        if authenticated:
            if not self._api_key:
                raise ReadlintError(
                    "authentication_required", _RECOVERY["authentication_required"]
                )
            headers["Authorization"] = f"Bearer {self._api_key}"
        for attempt in range(self.max_retries + 1):
            response = None
            try:
                response = self._http.request(
                    method, self.base_url + path, headers=headers, **kwargs
                )
            except httpx.RequestError:
                if not retry or attempt == self.max_retries:
                    raise ReadlintError(
                        "network_error",
                        "No reliable response. Check your connection; for a submission reuse its key and identical input.",
                    ) from None
            else:
                if 200 <= response.status_code < 300:
                    if response.status_code == 204:
                        return None
                    try:
                        body = response.json()
                        if not isinstance(body, dict):
                            raise TypeError("expected object")
                        return body
                    except (ValueError, TypeError):
                        raise ReadlintError(
                            "invalid_response",
                            "The service returned invalid JSON; retry later with the same submission key.",
                        ) from None
                # A stored failed evaluation is a terminal result, not a retryable gateway failure.
                try:
                    body = response.json()
                except ValueError:
                    body = None
                if isinstance(body, dict) and body.get("status") == "failed":
                    try:
                        evaluation_id = str(UUID(body["id"]))
                    except (KeyError, ValueError, TypeError, AttributeError):
                        evaluation_id = None
                    raise ReadlintError(
                        "evaluation_failed",
                        "Evaluation failed. Read its ID for details; a deliberate new attempt needs a new idempotency key.",
                        status=response.status_code,
                        evaluation_id=evaluation_id,
                    )
                if (
                    not retry
                    or response.status_code not in {429, 502, 503, 504}
                    or attempt == self.max_retries
                ):
                    raise _problem(response)
            delay = _retry_delay(response, attempt)
            if delay is None:
                assert response is not None
                raise _problem(response)
            time.sleep(delay)
        raise AssertionError("unreachable")

    def evaluate(
        self,
        article: str,
        *,
        idempotency_key: str,
        title: str | None = None,
        description: str = "",
    ) -> Evaluation:
        if not re.fullmatch(r"[!-~]{1,255}", idempotency_key):
            raise ValueError(
                "idempotency_key must be 1–255 printable ASCII characters without spaces."
            )
        return cast(
            Evaluation,
            self._request(
                "POST",
                "/v1/evaluations",
                retry=True,
                headers={"Idempotency-Key": idempotency_key},
                json={"article": article, "title": title, "description": description},
            ),
        )

    def list_evaluations(
        self, *, limit: int | None = None, offset: int = 0
    ) -> EvaluationPage:
        if offset < 0 or (limit is not None and limit < 1):
            raise ValueError("offset must be nonnegative and limit must be positive.")
        params = {"offset": offset}
        if limit is not None:
            params["limit"] = limit
        return cast(
            EvaluationPage,
            self._request("GET", "/v1/evaluations", params=params, retry=True),
        )

    def get_evaluation(self, evaluation_id: str) -> Evaluation:
        return cast(
            Evaluation,
            self._request("GET", f"/v1/evaluations/{UUID(evaluation_id)}", retry=True),
        )

    def delete_evaluation(self, evaluation_id: str) -> None:
        self._request("DELETE", f"/v1/evaluations/{UUID(evaluation_id)}")
