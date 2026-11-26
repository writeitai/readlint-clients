# readlint.com TypeScript SDK

Typed evaluation and device-authorization methods for Node.js 22 and later.

```sh
npm install https://github.com/writeitai/readlint-clients/releases/download/v0.2.0/writeitai-readlint-0.1.0.tgz
```

```ts
import { Readlint } from "@writeitai/readlint";

const client = new Readlint(); // Set READLINT_API_KEY on your server.
const result = await client.evaluate("# Article\n\nUseful text.", {
  idempotencyKey: "article-v1", // Retain this key and identical input for retries.
});
console.log(result.id, result.report);
```

See the [SDK guide](https://github.com/writeitai/readlint-clients/blob/main/docs/typescript.md)
for authentication, pagination, errors, retries and device login, and the
[development guide](https://github.com/writeitai/readlint-clients/blob/main/docs/development.md)
for source builds and contract checks.

Licensed under Apache-2.0. Transport adapted from `writeitai/mountable`
`d936589b1e200e347f03dfc32609c5d368668ae2`.
