# Python SDK

Install the public release into a clean Python 3.11+ environment:

```sh
python -m venv .venv
.venv/bin/python -m pip install https://github.com/writeitai/readlint-clients/releases/download/v0.3.0/readlint-0.3.0-py3-none-any.whl
```

Set `READLINT_API_KEY` to a key created in the
[web app](https://readlint.com/app/api-keys). The SDK accepts an explicit
`api_key` first, then this environment variable. It does not read CLI logins.

```python
from readlint import Readlint, ReadlintError

with Readlint() as client:
    result = client.evaluate(
        "# My article\n\nText for readers.",
        idempotency_key="my-article-2026-11-26",
        title="My article",
        description="An example",
    )
    print(result["id"], result["status"])
    page = client.list_evaluations(limit=20, offset=0)
    print(page["next_offset"])
    saved = client.get_evaluation(result["id"])
    if saved["report"] is not None:
        print(saved["report"]["prose_blocks"])
    client.delete_evaluation(result["id"])
```

Responses are JSON dictionaries described by exported `Evaluation`,
`EvaluationSummary`, `EvaluationPage` and `EvaluationReport` types. Dates are
RFC 3339 strings. `py.typed` is included. `ReadlintError` exposes `code`,
`message`, `status` (None for transport errors) and `evaluation_id` (when
available). It never includes the key or raw server error body.

```python
try:
    with Readlint(api_key="invalid", max_retries=0) as client:
        client.list_evaluations()
except ReadlintError as error:
    assert error.status == 401
    assert error.code == "authentication_required"
    print(error.message)  # Replace the key or sign in again.
```

Use a context manager or call `close()` to release connections. Optional
constructor arguments are `base_url`, `timeout` (120 seconds), `max_retries`
(2), and an httpx `transport` for controlled tests. `READLINT_BASE_URL` is the
default when `base_url` is omitted.

Read the [CLI retry and error reference](cli.md#retry-rules) before retrying
writes. `evaluate` requires an explicit `idempotency_key`, so your program can
persist it before sending. Automatic retries reuse the same key and body.
An HTTP 202 returns `status="running"`; call `get_evaluation` to check it.
A stored failed evaluation raises `evaluation_failed` with its ID; subsequent
`get_evaluation` returns its stored failed status and error code.
