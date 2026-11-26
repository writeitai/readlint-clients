# TypeScript SDK

Requires Node.js 22 or later. Install the public npm archive; no private source
or runtime dependencies are needed:

```sh
npm install https://github.com/writeitai/readlint-clients/releases/download/v0.2.0/writeitai-readlint-0.1.0.tgz
```

The package name is `@writeitai/readlint`. This version is distributed through
GitHub Releases. Set `READLINT_API_KEY` to a key from the web app or the
[CLI device login](cli.md). Keep keys on your server; never include an account
key in a public browser bundle.

```ts
import { Readlint, ReadlintError, type Evaluation } from "@writeitai/readlint";

const client = new Readlint(); // READLINT_API_KEY
try {
  const result: Evaluation = await client.evaluate("# Article\n\nUseful text.", {
    idempotencyKey: "article-2026-11-26-v1",
    title: "An example",
    description: "For new readers",
  });
  console.log(result.id, result.report?.prose_blocks);
  const page = await client.listEvaluations({limit: 10});
  console.log(page.items.map(item => item.id));
  console.log((await client.getEvaluation(result.id)).status);
  await client.deleteEvaluation(result.id);
} catch (error) {
  if (error instanceof ReadlintError) console.error(error.code, error.status, error.message);
  else throw error;
}
```

`apiKey` and `baseUrl` constructor options override `READLINT_API_KEY` and
`READLINT_BASE_URL`. The default origin is `https://readlint.com`; custom origins
must use HTTPS, with HTTP allowed only on loopback. The SDK refuses redirects.
`timeoutMs` defaults to 120000 per attempt, including reading the body.
`maxRetries` defaults to 2. `fetch` can supply a compatible custom transport.

Results use the API's JSON field names. `Evaluation`, `EvaluationSummary`,
`EvaluationPage`, `EvaluationReport`, `CheckResult`, `ProseResult`, and
`PhraseResult` are exported types. Timestamps are strings. A report is nullable
for unfinished or failed evaluations. `listEvaluations` returns one page, with
`next_offset` for the next call's `offset`; use `null` as the stop condition.

## Failures and retries

`ReadlintError` exposes `code`, `status`, `evaluationId` and a sanitized recovery
message. `status` is null after network failure. Missing or invalid credentials
produce `authentication_required`; correct the key before retrying. Invalid
local options throw `TypeError`. HTTP validation failures produce
`validation_error` or the documented API code.

Reads and submissions with an explicit idempotency key retry network errors and
HTTP 429, 502, 503 and 504. Retries preserve the exact body and key. They use
exponential waits and honor numeric or HTTP-date `Retry-After`; waits above
60 seconds return an error so the caller can wait longer. Deletes and device
requests are not retried automatically. After an uncertain delete, read the ID
and reconcile; a 404 means it is absent.

Keep the submission key and the identical article, title and description. After
an uncertain submission, call `evaluate` again with that same input and key to
retrieve the stored outcome. Changing input under that key produces
`idempotency_key_reused`. A stored failed evaluation returns
`evaluation_failed`, with its safe UUID in `evaluationId`; it is terminal and
is not retried. Read that ID for details. A deliberate new attempt needs a new
key and may use more evaluation credit.

## Device authorization

The SDK also exposes `createDeviceCode({hostname, os})` and
`createDeviceToken(deviceCode)`. These form requests do not send a bearer key.
Display the returned `verification_uri_complete` and `user_code`. Poll at the
returned `interval` until `expires_in` elapses. On `authorization_pending`, wait
and poll again; on `slow_down`, increase the interval by at least five seconds.
On `access_denied`, `expired_token` or `invalid_grant`, start again. The SDK
performs one token request per call and never persists the returned key.
Create a new `Readlint({apiKey: token.access_token})` after approval. Applications
that need saved credentials can use the CLI instead.
