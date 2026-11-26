import json
import sys

import httpx
import pytest

from readlint.cli import main


@pytest.mark.parametrize(
    "args",
    [
        ["get", "not-a-uuid"],
        ["--unknown", "rlk_secret"],
        ["list", "--limit", "not-a-number"],
        ["list", "--base-url", "https://example.com:bad"],
    ],
)
def test_invalid_arguments_are_recoverable_json(args, monkeypatch, capsys):
    monkeypatch.setattr(
        sys, "argv", ["readlint", "--json", "--api-key", "rlk_secret", *args]
    )
    assert main() == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err)["error"]["code"] == "invalid_input"
    assert "rlk_secret" not in output.err


def test_exhausted_network_failure_is_sanitized(monkeypatch, capsys):
    def fail(*args, **kwargs):
        raise httpx.ConnectError("contains rlk_secret")

    monkeypatch.setattr(httpx.Client, "request", fail)
    monkeypatch.setattr("readlint.client.time.sleep", lambda _: None)
    monkeypatch.setattr(
        sys, "argv", ["readlint", "list", "--json", "--api-key", "rlk_secret"]
    )
    assert main() == 1
    output = capsys.readouterr()
    assert output.out == ""
    problem = json.loads(output.err)["error"]
    assert problem["code"] == "network_error"
    assert "connection" in problem["message"]
    assert "rlk_secret" not in output.err


@pytest.mark.parametrize(
    "status,code",
    [(401, "authentication_required"), (422, "validation_error"), (503, "api_error")],
)
def test_api_errors_and_recovery(monkeypatch, capsys, status, code):
    monkeypatch.setattr(
        httpx.Client,
        "request",
        lambda *a, **kw: httpx.Response(
            status, json={"detail": {"code": "rlk_secret"}}
        ),
    )
    monkeypatch.setattr("readlint.client.time.sleep", lambda _: None)
    monkeypatch.setattr(
        sys, "argv", ["readlint", "list", "--json", "--api-key", "rlk_secret"]
    )
    assert main() == 1
    output = capsys.readouterr()
    assert output.out == ""
    error = json.loads(output.err)["error"]
    assert error["code"] == code
    assert error["message"]
    assert "rlk_secret" not in output.err


@pytest.mark.parametrize("command", ["check", "evaluate"])
def test_check_and_evaluate_are_the_same_submission(
    command, monkeypatch, capsys, tmp_path
):
    article = tmp_path / "post.md"
    article.write_text("# Article")
    calls = []

    def submit(*args, **kwargs):
        calls.append(kwargs)
        return httpx.Response(200, json={"id": "64dfbf5a-2016-41a0-ad7f-b6808929b5ae"})

    monkeypatch.setattr(httpx.Client, "request", submit)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "readlint",
            command,
            str(article),
            "--json",
            "--api-key",
            "rlk_test",
            "--idempotency-key",
            "same-key",
        ],
    )
    assert main() == 0
    assert len(calls) == 1
    assert calls[0]["headers"]["Idempotency-Key"] == "same-key"
    assert calls[0]["json"]["article"] == "# Article"
    output = capsys.readouterr()
    assert json.loads(output.out)["id"] == "64dfbf5a-2016-41a0-ad7f-b6808929b5ae"
    assert "same-key" in output.err
