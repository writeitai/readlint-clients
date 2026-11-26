# readlint.com

TypeScript SDK, CLI and stdio MCP server for Node.js 22 and later.

```sh
npx readlint.com check article.md --json
npx readlint.com mcp
```

After the first npm publication, install with `npm install readlint.com`.
Until then, run the CLI with `npx --yes --package=<archive-URL> readlint`
or install the public archive below. Python users can use `uvx readlint`
after PyPI publication, or the versioned wheel in the CLI guide.

```sh
npm install https://github.com/writeitai/readlint-clients/releases/download/v0.3.0/readlint.com-0.3.0.tgz
```

```ts
import { Readlint } from "readlint.com";

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
