import json

import httpx
import pytest

from readlint.mcp import TOOLS, call_tool


def test_catalogue_budget_and_explicit_tools():
    catalogue = json.dumps([t.model_dump(exclude_none=True) for t in TOOLS])
    assert len(catalogue.encode()) <= 6000
    assert {t.name for t in TOOLS} == {
        "evaluate_article",
        "get_evaluation",
        "list_evaluations",
        "delete_evaluation",
    }


@pytest.mark.parametrize(
    "name,arguments",
    [
        ("rlk_secret", {}),
        ("get_evaluation", {"evaluation_id": "rlk_secret"}),
        ("list_evaluations", {"limit": "rlk_secret"}),
        ("list_evaluations", {"api_key": "rlk_secret"}),
        (
            "evaluate_article",
            {"article": "text", "idempotency_key": "bad key rlk_secret"},
        ),
        ("evaluate_article", {"article": "", "idempotency_key": "key"}),
        ("evaluate_article", {"article": "text", "idempotency_key": "rlk_secret\n"}),
    ],
)
def test_invalid_input_sanitized(name, arguments):
    result = call_tool(name, arguments, api_key="rlk_secret")
    assert result.isError
    assert result.structuredContent is not None
    assert result.structuredContent["error"]["code"] == "invalid_input"
    assert "rlk_secret" not in result.model_dump_json()


@pytest.mark.parametrize(
    "status,code",
    [(401, "authentication_required"), (422, "validation_error"), (503, "api_error")],
)
def test_api_failure_and_recovery(monkeypatch, status, code):
    calls = []

    def request(*args, **kwargs):
        calls.append(kwargs)
        return httpx.Response(status, json={"detail": {"code": "rlk_secret"}})

    monkeypatch.setattr(httpx.Client, "request", request)
    monkeypatch.setattr("readlint.client.time.sleep", lambda _: None)
    result = call_tool(
        "evaluate_article",
        {"article": "draft", "idempotency_key": "retained"},
        api_key="rlk_secret",
    )
    assert result.isError
    assert result.structuredContent is not None
    assert result.structuredContent["error"]["code"] == code
    assert result.structuredContent["error"]["idempotency_key"] == "retained"
    assert "rlk_secret" not in result.model_dump_json()
    assert len(calls) == (3 if status == 503 else 1)


def test_missing_credentials(monkeypatch, tmp_path):
    monkeypatch.delenv("READLINT_API_KEY", raising=False)
    monkeypatch.setattr("readlint.auth.credentials_path", lambda: tmp_path / "missing")
    result = call_tool("list_evaluations", {})
    assert result.isError
    assert result.structuredContent is not None
    assert result.structuredContent["error"]["code"] == "authentication_required"
    assert "readlint login" in result.structuredContent["error"]["message"]


def test_unexpected_error_does_not_echo_secrets(monkeypatch):
    def request(*args, **kwargs):
        raise RuntimeError("rlk_secret")

    monkeypatch.setattr(httpx.Client, "request", request)
    result = call_tool("list_evaluations", {}, api_key="rlk_secret")
    assert result.isError
    assert result.structuredContent is not None
    assert result.structuredContent["error"]["code"] == "internal_error"
    assert "rlk_secret" not in result.model_dump_json()
