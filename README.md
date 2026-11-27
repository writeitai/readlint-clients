# readlint.com clients

readlint.com reviews articles and points out where readers might get lost. It
flags unexplained terms, missing reasons to care, and ideas that appear out of
order.

With Node.js 22+, run:

```sh
npx readlint.com --help
npx readlint.com login
npx readlint.com list --limit 25 --offset 0 --json
```

Python 3.11+ users with uv can run the same commands with `uvx readlint`.
Install the SDK with `pip install readlint` or `npm install readlint.com`.

Follow the maintained [CLI](https://readlint.com/docs/cli),
[Python SDK](https://readlint.com/docs/python),
[TypeScript SDK](https://readlint.com/docs/typescript),
[MCP](https://readlint.com/docs/mcp) and
[skill](https://readlint.com/docs/skills) guides for prerequisites,
authentication, examples, expected results and recovery.

Install the skill with `npx skills add writeitai/readlint-clients --skill readlint`.
See [development notes](docs/development.md) for local checks and releases.

To contribute, read [AGENTS.md](AGENTS.md) and the
[shared project skills](.agents/skills).

Licensed under [Apache 2.0](LICENSE).
