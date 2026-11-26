# CLI

With Node.js 22 or newer, run the CLI without installing it globally:

```sh
npx readlint.com check article.md --json
npx readlint.com login
npx readlint.com --help
```

The `readlint.com` npm package contains the TypeScript SDK, CLI and MCP server.
The registry commands above become available after the first npm publication.
Until then, run the same package from its public release archive:

```sh
npx --yes --package=https://github.com/writeitai/readlint-clients/releases/download/v0.3.0/readlint.com-0.3.0.tgz readlint --help
```

For Python 3.11+ and uv, use `uvx readlint` after its PyPI publication, or the
versioned public wheel:

```sh
uvx --from https://github.com/writeitai/readlint-clients/releases/download/v0.3.0/readlint-0.3.0-py3-none-any.whl readlint --help
```

Install permanently with `npm install -g readlint.com` after npm publication,
or `uv tool install <wheel-URL>`. The examples below use the installed
`readlint` command; prefix them with `npx readlint.com` or `uvx readlint` as
appropriate. `check` and `evaluate` submit the same request in both clients.

## Sign in

On macOS or Linux:

```sh
readlint login
```

Open the URL printed on stderr, sign in, check the displayed code and approve
it. Login works without a terminal prompt. The CLI waits for approval and
saves a 30-day API key in an owner-only file, then prints `{"signed_in": true}`.
It handles pending approval, slow-down responses and network backoff. Denial,
expiry or signing out of the approving web session before exchange cancels
login. Run `readlint login` again to get a new code.

Credentials are stored at `~/Library/Application Support/readlint/credentials.json`
on macOS or `${XDG_CONFIG_HOME:-~/.config}/readlint/credentials.json` on Linux.
They are bound to the API origin and replaced atomically with mode `0600`.

For scripts, CI and Windows, create a key at
[API keys](https://readlint.com/app/api-keys) and set `READLINT_API_KEY` through
your secret manager. `--api-key` also accepts a key. Precedence is flag,
environment, saved login. Prefer the environment so keys stay out of shell
history and process arguments. The SDK uses an explicit key or the environment.

`readlint logout` removes the saved local login. It does **not** revoke the
server-side key or unset your environment. Revoke the key in the web app to
stop all copies immediately.

## Evaluate an article

```sh
readlint evaluate article.md --idempotency-key article-2026-11-26 --json > result.json
readlint list --limit 20 --offset 0 --json
readlint get EVALUATION_UUID --json
readlint delete EVALUATION_UUID --json
```

`evaluate -` reads UTF-8 Markdown or MDX from stdin. Optional `--title` and
`--description` override article metadata. Evaluation requires account access
and credit. A report can contain findings while the command still succeeds.
Findings are review results, not command failures.

Evaluation output contains `id`, `title`, `created_at`, `expires_at`, `status`,
`error_code` and `report`. `status` is `running`, `complete` or `failed`.
A running evaluation has no report yet; use `get` to check it. A report contains
article checks, prose blocks, banned phrases, the model and input-token count.
`list` returns `items` and `next_offset` (null at the end). `delete` returns
`{"deleted": true, "id": "..."}`. Stored evaluations expire at `expires_at`.

## JSON and errors

`--json` works before or after the command. Successful stdout is one JSON
object and exit status is zero. Without `--json`, output is indented JSON.
Diagnostics, login instructions and submission keys go to stderr. Nothing
prompts on stdin. Failures leave stdout empty and exit with status 1;
argument errors, authentication failures and API failures follow this rule.
Help and version flags exit zero.

The final stderr line in JSON mode is `{"error": {...}}` with `code` and
`message`; API errors also carry `status` (null for a network failure) and
`evaluation_id` (when a failed evaluation ID was returned). A submission error
also includes `idempotency_key`. Earlier stderr lines can contain diagnostics.
Keys and request bodies are omitted from errors.

Common recovery actions:

| Code | Action |
| --- | --- |
| `authentication_required` | Run login, or replace an expired/revoked key. |
| `invalid_input`, `validation_error` | Check help, file encoding, UUID and options. |
| `evaluation_not_allowed` | Contact support@readlint.com for account access. |
| `evaluation_credit_exhausted` | Check account credit in the web app. |
| `evaluation_context_exceeded` | Shorten the article and use a new submission key. |
| `idempotency_key_reused` | Restore the exact original input or choose a new key. |
| `evaluation_failed` | Read `evaluation_id`; a deliberate new attempt needs a new key. |
| `network_error`, `rate_limited`, `api_error` | Follow the retry rules below. |

## Retry rules

The client retries reads and evaluation submissions at most twice after a
network failure or HTTP 429, 502, 503 or 504. It waits 1 then 2 seconds, or
honors `Retry-After` seconds/date. If the server asks for more than 60 seconds,
it stops instead of retrying early. A stored failed evaluation is terminal
and is not retried. Authentication and validation errors are not retried.
Set SDK `max_retries=0` to disable transport retries.

Every submission has an idempotency key. If you omit `--idempotency-key`, the
CLI generates one and prints it on stderr **before sending**. After a timeout
or interruption, reuse that key with exactly the same article, title and
description. The server returns the existing evaluation instead of charging
for a duplicate. Do not change the key just because an answer was lost.
Keep the key until the outcome is known. After the evaluation's retention
expires, its key can be reused by the service: reconcile before retrying an
old submission. Pagination uses offsets; new/deleted records can shift pages.

Deletes are sent once. After a lost delete response, `get` the same ID:
`evaluation_not_found` confirms it is no longer stored. Retry delete only if
it still exists. Device-code creation and token exchange are sent once per
poll; if an exchange answer is lost, the code may already be used. Run login
again and revoke unused CLI keys in the web app.

`READLINT_BASE_URL` or `--base-url` changes the API origin. HTTPS is required,
except HTTP on loopback for tests. Redirects are never followed with your
credential. `--timeout` sets the HTTP timeout in seconds (default 120).
