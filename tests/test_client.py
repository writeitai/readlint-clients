import json

import httpx
import pytest

from readlint import Readlint, ReadlintError

EVALUATION_ID = "64dfbf5a-2016-41a0-ad7f-b6808929b5ae"
RESULT = {
    "id": EVALUATION_ID,
    "title": "An article",
    "created_at": "2026-11-26T10:00:00Z",
    "expires_at": "2026-12-26T10:00:00Z",
    "status": "complete",
    "error_code": None,
    "report": {
        "title": "An article",
        "description": "",
        "article_checks": [],
        "prose_blocks": [],
        "banned_phrases": [],
        "omitted_computed_jsx": [],
        "model": "test",
        "input_tokens": 12,
        "expires_at": "2026-12-26T10:00:00Z",
    },
}


def test_core_workflow():
    calls = []

    def serve(request):
        calls.append(request)
        assert request.headers["Authorization"] == "Bearer rlk_test"
        if request.method == "DELETE":
            return httpx.Response(204)
        if request.method == "POST":
            assert json.loads(request.content) == {
                "article": "# Example",
                "title": None,
                "description": "",
            }
            assert request.headers["Idempotency-Key"] == "test-1"
        if request.url.path == "/v1/evaluations" and request.method == "GET":
            assert dict(request.url.params) == {"offset": "2", "limit": "3"}
            return httpx.Response(200, json={"items": [RESULT], "next_offset": 5})
        return httpx.Response(200, json=RESULT)

    with Readlint("rlk_test", transport=httpx.MockTransport(serve)) as client:
        assert client.evaluate("# Example", idempotency_key="test-1") == RESULT
        assert client.list_evaluations(limit=3, offset=2)["next_offset"] == 5
        report = client.get_evaluation(EVALUATION_ID)["report"]
        assert report is not None
        assert report["input_tokens"] == 12
        assert client.delete_evaluation(EVALUATION_ID) is None
    assert len(calls) == 4


@pytest.mark.parametrize("kind", ["timeout", "503", "429"])
def test_submission_retries_same_bytes_and_key(monkeypatch, kind):
    calls = []
    sleeps = []
    monkeypatch.setattr("readlint.client.time.sleep", sleeps.append)

    def serve(request):
        calls.append(request)
        if len(calls) == 1:
            if kind == "timeout":
                raise httpx.ReadTimeout("rlk_secret should not escape")
            return httpx.Response(int(kind), headers={"Retry-After": "2"})
        return httpx.Response(200, json=RESULT)

    with Readlint("key", transport=httpx.MockTransport(serve)) as client:
        assert client.evaluate("article", idempotency_key="same-key") == RESULT
    assert sleeps == [2 if kind != "timeout" else 1]
    assert calls[0].content == calls[1].content
    assert calls[0].headers["Idempotency-Key"] == calls[1].headers["Idempotency-Key"]


def test_long_retry_after_is_not_retried(monkeypatch):
    def no_sleep(_):
        pytest.fail("must not retry early")

    monkeypatch.setattr("readlint.client.time.sleep", no_sleep)
    with (
        Readlint(
            "key",
            transport=httpx.MockTransport(
                lambda r: httpx.Response(429, headers={"Retry-After": "120"})
            ),
        ) as client,
        pytest.raises(ReadlintError, match="rate_limited"),
    ):
        client.list_evaluations()


@pytest.mark.parametrize(
    "status,body,code",
    [
        (
            401,
            {"detail": {"code": "authentication_required"}},
            "authentication_required",
        ),
        (
            422,
            {"detail": {"code": "validation_error", "input": "rlk_secret"}},
            "validation_error",
        ),
        (500, {"detail": {"code": "rlk_secret"}}, "api_error"),
        (500, ["rlk_secret"], "api_error"),
    ],
)
def test_errors_are_sanitized(status, body, code):
    with (
        Readlint(
            "rlk_secret",
            transport=httpx.MockTransport(lambda r: httpx.Response(status, json=body)),
        ) as client,
        pytest.raises(ReadlintError) as found,
    ):
        client.list_evaluations()
    assert found.value.code == code
    assert found.value.status == status
    assert "rlk_secret" not in repr(found.value.as_dict())


def test_terminal_failure_not_retried():
    requests = []

    def serve(request):
        requests.append(request)
        return httpx.Response(
            502, json={**RESULT, "status": "failed", "error_code": "upstream_error"}
        )

    with (
        Readlint("key", transport=httpx.MockTransport(serve)) as client,
        pytest.raises(ReadlintError) as found,
    ):
        client.evaluate("text", idempotency_key="once")
    assert found.value.evaluation_id == EVALUATION_ID
    assert len(requests) == 1


def test_redirects_do_not_forward_credentials():
    calls = []

    def serve(request):
        calls.append(request)
        return httpx.Response(307, headers={"Location": "https://other.invalid"})

    with (
        Readlint("key", transport=httpx.MockTransport(serve)) as client,
        pytest.raises(ReadlintError),
    ):
        client.list_evaluations()
    assert len(calls) == 1


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "https://user:pass@example.com",
        "https://example.com?token=x",
        "https://example.com/path",
        "file:///tmp/test",
    ],
)
def test_unsafe_origins_rejected(url):
    with pytest.raises(ValueError):
        Readlint("secret", base_url=url)


def test_input_validation_before_network():
    with Readlint(
        "key",
        transport=httpx.MockTransport(lambda r: pytest.fail("unexpected request")),
    ) as client:
        with pytest.raises(ValueError):
            client.get_evaluation("../auth")
        with pytest.raises(ValueError):
            client.evaluate("text", idempotency_key="has spaces")
        with pytest.raises(ValueError):
            client.list_evaluations(limit=0)


def test_missing_credentials(monkeypatch):
    monkeypatch.delenv("READLINT_API_KEY", raising=False)
    with Readlint() as client, pytest.raises(ReadlintError, match="readlint login"):
        client.list_evaluations()
