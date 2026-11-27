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

from readlint.types import (
    AgentPermissions,
    BillingCancellation,
    BillingOrder,
    BillingPortal,
    BillingQuote,
    BillingStatus,
    Evaluation,
    EvaluationPage,
)

DEFAULT_BASE_URL = "https://readlint.com"

_RECOVERY = {
    "authentication_required": "Run `readlint login` or set a valid READLINT_API_KEY.",
    "evaluation_credit_exhausted": "Check your evaluation credit in the web app.",
    "evaluation_not_allowed": "Ask support@readlint.com for evaluation access.",
    "evaluation_disabled": "Try again later with the same idempotency key and article.",
    "evaluation_context_exceeded": "Shorten the article and submit with a new key.",
    "evaluation_not_found": "List evaluations to find an unexpired evaluation ID.",
    "idempotency_key_reused": "Reuse the original key and identical input to recover its outcome; use a new key only for a deliberate new instruction.",
    "agent_orders_unavailable": "API-key paid orders are not available yet. Use the owner Billing page.",
    "billing_disabled": "Billing is not available. Read billing status before trying again.",
    "quote_expired": "Read billing status, then request a fresh quote for a new instruction.",
    "quote_changed": "Review a fresh quote and its disclosure before confirming a new instruction.",
    "quote_not_found": "Use a quote belonging to this account.",
    "terms_version_mismatch": "Use the Terms version in a fresh quote.",
    "paid_order_consent_required": "Explicit paid-order confirmation is required.",
    "paid_order_already_confirmed": "Read the current order in billing status.",
    "save_card_first": "Save a payment method using the returned payment link.",
    "billing_address_required": "Complete the billing address using the returned payment link.",
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
        action: str | None = None,
        settings_url: str | None = None,
        retryable: bool | None = None,
        action_url: str | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.status = status
        self.evaluation_id = evaluation_id
        self.action = action
        self.settings_url = settings_url
        self.retryable = retryable
        self.action_url = action_url
        super().__init__(message)

    def as_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "code": self.code,
            "message": self.message,
            "status": self.status,
            "evaluation_id": self.evaluation_id,
        }
        for field in ("action", "settings_url", "retryable", "action_url"):
            if (value := getattr(self, field)) is not None:
                result[field] = value
        return result


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


def _problem(response: httpx.Response, base_url: str) -> ReadlintError:
    try:
        body = response.json()
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        body = {}
    detail = body.get("detail")
    code = detail.get("code") if isinstance(detail, dict) else body.get("error")
    # Only exact known denial sentences may cross the sanitized error boundary.
    if (
        response.status_code == 403
        and isinstance(detail, dict)
        and code == "agent_permission_disabled"
    ):
        for label in (
            "Agents can start trials",
            "Agents can confirm paid orders",
            "Agents can cancel plans",
        ):
            message = f'The account has turned off "{label}".'
            action = f'Ask the account owner to enable "{label}" in Settings → Agent permissions.'
            if (
                detail.get("message") == message
                and detail.get("action") == action
                and detail.get("settings_url") == "/app/settings#agent-permissions"
                and detail.get("retryable") is False
            ):
                return ReadlintError(
                    code,
                    message,
                    status=403,
                    action=action,
                    settings_url=base_url + "/app/settings#agent-permissions",
                    retryable=False,
                )
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
    action_url = None
    if code in {"save_card_first", "billing_address_required"} and isinstance(
        detail, dict
    ):
        value = detail.get("action_url")
        if isinstance(value, str):
            try:
                url = urlsplit(value)
                if (
                    url.scheme == "https"
                    and url.netloc in {"billing.stripe.com", "checkout.stripe.com"}
                    and url.username is None
                    and url.password is None
                    and not url.fragment
                    and not any(ord(c) < 33 for c in value)
                ):
                    action_url = value
            except ValueError:
                pass
    return ReadlintError(
        code,
        f"HTTP {response.status_code}: {code}. {recovery}",
        status=response.status_code,
        action_url=action_url,
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
                    raise _problem(response, self.base_url)
            delay = _retry_delay(response, attempt)
            if delay is None:
                assert response is not None
                raise _problem(response, self.base_url)
            time.sleep(delay)
        raise AssertionError("unreachable")

    def get_agent_permissions(self) -> AgentPermissions:
        """Read account-wide policy. Only the owner browser may change it."""
        return cast(
            AgentPermissions, self._request("GET", "/v1/agent-permissions", retry=True)
        )

    def get_billing_status(self) -> BillingStatus:
        return cast(
            BillingStatus, self._request("GET", "/v1/billing/status", retry=True)
        )

    def create_billing_quote(self) -> BillingQuote:
        """Return a nonbinding quote with the complete disclosure."""
        return cast(BillingQuote, self._request("POST", "/v1/billing/quote"))

    def confirm_billing_order(
        self,
        quote_id: str,
        *,
        terms_version: str,
        paid_order_confirmed: bool,
        idempotency_key: str,
    ) -> BillingOrder:
        """Explicit acceptance. Never automatically retries a financial instruction."""
        if paid_order_confirmed is not True:
            raise ValueError("paid_order_confirmed must be explicitly True.")
        return cast(
            BillingOrder,
            self._request(
                "POST",
                "/v1/billing/order",
                headers={"Idempotency-Key": str(UUID(idempotency_key))},
                json={
                    "quote_id": str(UUID(quote_id)),
                    "terms_version": terms_version,
                    "paid_order_confirmed": True,
                },
            ),
        )

    def cancel_billing_plan(self, *, idempotency_key: str) -> BillingCancellation:
        return cast(
            BillingCancellation,
            self._request(
                "POST",
                "/v1/billing/cancel",
                headers={"Idempotency-Key": str(UUID(idempotency_key))},
                json={},
            ),
        )

    def create_billing_portal(self) -> BillingPortal:
        return cast(BillingPortal, self._request("POST", "/v1/billing/portal"))

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
