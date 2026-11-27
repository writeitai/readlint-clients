"""Financial writes are explicit, non-retried and keep safe recovery details."""

import json
import sys

import httpx
import pytest

from readlint import Readlint, ReadlintError, cli

ID = "64dfbf5a-2016-41a0-ad7f-b6808929b5ae"


def denial(label="Agents can confirm paid orders"):
    return {
        "code": "agent_permission_disabled",
        "message": f'The account has turned off "{label}".',
        "action": f'Ask the account owner to enable "{label}" in Settings → Agent permissions.',
        "settings_url": "/app/settings#agent-permissions",
        "retryable": False,
    }


@pytest.mark.parametrize("kind", ["order", "cancel"])
@pytest.mark.parametrize("failure", ["timeout", "503", "403"])
def test_financial_writes_are_not_automatically_retried(kind, failure):
    calls = []

    def serve(request):
        calls.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("PRIVATE_SECRET")
        return httpx.Response(
            int(failure),
            json={
                "detail": denial()
                if failure == "403"
                else {"code": "agent_orders_unavailable"}
            },
        )

    with (
        Readlint("key", transport=httpx.MockTransport(serve)) as client,
        pytest.raises(ReadlintError),
    ):
        if kind == "order":
            client.confirm_billing_order(
                ID,
                terms_version="2026-11-25",
                paid_order_confirmed=True,
                idempotency_key=ID,
            )
        else:
            client.cancel_billing_plan(idempotency_key=ID)
    assert len(calls) == 1
    assert calls[0].headers["Idempotency-Key"] == ID


@pytest.mark.parametrize(
    "field,value",
    [
        (None, None),
        ("message", "PRIVATE_SECRET"),
        ("action", "PRIVATE_SECRET"),
        ("settings_url", "https://evil.test/PRIVATE_SECRET"),
        ("retryable", True),
    ],
)
def test_known_permission_fields_only(field, value):
    detail = denial()
    if field:
        detail[field] = value
    with (
        Readlint(
            "key",
            base_url="https://sandbox.readlint.com",
            transport=httpx.MockTransport(
                lambda _: httpx.Response(403, json={"detail": detail})
            ),
        ) as client,
        pytest.raises(ReadlintError) as error,
    ):
        client.cancel_billing_plan(idempotency_key=ID)
    problem = error.value.as_dict()
    if field is None:
        assert problem["code"] == "agent_permission_disabled"
        assert (
            problem["settings_url"]
            == "https://sandbox.readlint.com/app/settings#agent-permissions"
        )
        assert problem["retryable"] is False and problem["action"] == detail["action"]
    else:
        assert problem["code"] == "api_error" and "settings_url" not in problem
        assert "PRIVATE_SECRET" not in str(problem)


@pytest.mark.parametrize(
    "url,safe",
    [
        ("https://billing.stripe.com/p/session/test", True),
        ("https://evil.test/secret", False),
        ("https://secret@billing.stripe.com/test", False),
        ("https://billing.stripe.com\\@evil.test/secret", False),
        ("http://billing.stripe.com/test", False),
    ],
)
def test_card_recovery_links_are_only_expected_stripe_origins(url, safe):
    with (
        Readlint(
            "key",
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    409, json={"detail": {"code": "save_card_first", "action_url": url}}
                )
            ),
        ) as client,
        pytest.raises(ReadlintError) as error,
    ):
        client.create_billing_quote()
    assert error.value.action_url == (url if safe else None)


@pytest.mark.parametrize("extra", [[], ["--yes"]])
def test_cli_requires_explicit_paid_flag(extra, monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "readlint",
            "billing",
            "order",
            "--json",
            "--quote-id",
            ID,
            "--terms-version",
            "2026-11-25",
            "--idempotency-key",
            ID,
            *extra,
        ],
    )

    def no_request(*args, **kwargs):
        pytest.fail("Unconfirmed order must not send HTTP")

    monkeypatch.setattr(httpx.Client, "request", no_request)
    assert cli.main() == 1
    assert json.loads(capsys.readouterr().err)["error"]["code"] == "invalid_input"


def test_cli_permission_error_preserves_safe_fields(monkeypatch, capsys):
    monkeypatch.setattr(
        httpx.Client,
        "request",
        lambda *args, **kwargs: httpx.Response(
            403, json={"detail": denial("Agents can cancel plans")}
        ),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "readlint",
            "billing",
            "cancel",
            "--json",
            "--api-key",
            "rlk_PRIVATE_SECRET",
            "--idempotency-key",
            ID,
        ],
    )
    assert cli.main() == 1
    output = capsys.readouterr()
    assert output.out == "" and "PRIVATE_SECRET" not in output.err
    result = json.loads(output.err.splitlines()[-1])["error"]
    assert (
        result["code"] == "agent_permission_disabled" and result["retryable"] is False
    )
    assert result["idempotency_key"] == ID


@pytest.mark.parametrize("value", [False, "true", 1, None])
def test_sdk_requires_literal_true(value):
    with (
        Readlint(
            "key", transport=httpx.MockTransport(lambda _: pytest.fail("no request"))
        ) as client,
        pytest.raises(ValueError),
    ):
        client.confirm_billing_order(
            ID,
            terms_version="2026-11-25",
            paid_order_confirmed=value,
            idempotency_key=ID,
        )


def test_invalid_mutation_key_is_not_echoed(monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "readlint",
            "billing",
            "cancel",
            "--json",
            "--api-key",
            "key",
            "--idempotency-key",
            "rlk_PRIVATE_SECRET",
        ],
    )
    assert cli.main() == 1
    assert "PRIVATE_SECRET" not in capsys.readouterr().err
