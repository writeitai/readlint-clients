# Development and releases

Run from this public repository:

```sh
uv sync --locked
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run pytest
uv build
uv run twine check dist/*
uv run python scripts/smoke.py
npm --prefix sdk/typescript ci
npm --prefix sdk/typescript run typecheck
npm --prefix sdk/typescript test
npm --prefix sdk/typescript run check:openapi
uv run python scripts/check_contract.py
uv run pytest contracts
npm pack ./sdk/typescript --pack-destination dist
node sdk/typescript/scripts/verify-package.mjs dist/writeitai-readlint-*.tgz
```

CI also installs each built wheel and source distribution in separate clean
virtual environments and runs `scripts/smoke.py` through the installed SDK and
CLI. Its local HTTP fixture checks device polling, saved credentials, a lost
submission response with one stored effect, CRUD, key precedence and errors.
The fixture never contacts readlint.com or a paid provider. CI covers Python
3.11 and 3.13 on Linux, and Python 3.13 on macOS. Saved login uses POSIX file
permissions; Windows users pass a key through the environment.

PR change detection uses `git diff --no-renames`. Only explicitly listed docs
paths skip heavy checks. Python and TypeScript changes gate their respective
jobs and the shared contract job. Schema changes gate the contract job. Unknown
paths and workflow changes run everything.
Classifier failure runs the gated jobs. Main pushes and `workflow_dispatch`
always run all checks, builds and installed-package verifications. All jobs
use GitHub-hosted runners. No Docker or private source is needed.

## Release

1. Change the package version in a reviewed PR and update `uv.lock`.
2. Wait for main CI, then push the matching `vX.Y.Z` tag at the merged commit.
3. The release workflow checks that the tag belongs to main and matches
   `pyproject.toml`, runs tests, builds the wheel/source archive, verifies clean
   installs, and publishes both plus the TypeScript npm archive with SHA-256 checksums
   to a GitHub Release.
4. Verify the public wheel URL in a clean environment using the installation
   instructions. Keep old versioned assets available.

The `release` GitHub environment restricts publication to version tags.
PyPI publishing is prepared in the same workflow and enabled only when
`PYPI_TRUSTED_PUBLISHING` is `true` on the repository. Before enabling it, add
PyPI's pending trusted publisher for project `readlint`, owner `writeitai`,
repository `readlint-clients`, workflow `release.yml`, environment `release`.
No upload token belongs in the repository. GitHub Releases are the current
install channel; do not document `pip install readlint` until its PyPI release
has been verified. Re-running a release verifies its required assets and checksums without
replacing them. A failed upload leaves a draft; an incomplete draft fails
verification and needs repair before publication. Never replace a published
version's bytes.

## Reused code

Adapted from public `writeitai/mountable` revision
`d936589b1e200e347f03dfc32609c5d368668ae2` (Apache-2.0):

- `cmd/mountable/login.go`: RFC 8628 polling and atomic owner-only credentials.
- `sdk/python/src/mountable_sdk/_client.py`: httpx transport, sanitized errors,
  context-manager lifecycle and explicit retry decisions.
- `.github/workflows/release.yml` and `sdk-release.yml`: tag releases, builds,
  clean install checks and OIDC publishing.

readlint.com uses an expiring account API key. It has no refresh-token,
filesystem, gateway, S3 or capture code. Account management, browser sessions
and browser approval stay in the hosted web app; client methods expose the
four evaluation operations and device login. Backend changes need coordinated
client updates. The response types follow the public `https://readlint.com/v1/openapi.json`
contract; backend implementation and production inventory stay private.


## TypeScript and API drift

The TypeScript SDK's version lives in `sdk/typescript/package.json`; its archive
is attached to the repository's next `vX.Y.Z` release alongside the Python
packages. Bump the Python release version for a new combined release, and bump
the TypeScript version whenever its published bytes change. npm registry
publishing is not configured; installation uses the exact public `.tgz` URL.
The clean consumer check installs that archive outside the source tree,
type-checks the documented example against its shipped declarations, and runs
CRUD, an authentication failure and a real HTTP lost-answer retry with one
stored effect. CI runs this on Node.js 22 and 24.

`contracts/openapi.json` is the public client export. Its source is
`https://readlint.com/v1/openapi.json`. `scripts/check_contract.py` fetches and
compares that current export on relevant PRs, every main/manual run and daily
scheduled CI. Fetch errors and mismatches fail the job; there is no fallback to
a cached schema. This public repository needs no private-repository token.
A backend PR can check its pre-deploy artifact locally:

```sh
uv run python scripts/check_contract.py --schema /path/to/readlint-openapi.json
```

The backend's exported CI artifact and its `--client` export produce the same
contract as the public URL. The public CI check observes the deployed backend;
a backend PR's unpublished schema must be passed with `--schema` before rollout.
For a coordinated schema change, update this snapshot from the fresh export,
reconcile the SDKs and CLI, regenerate with
`npm --prefix sdk/typescript run generate`, and run all checks above. The hosted
schema must match before client CI and releases pass.

`contracts/clients.json` is the explicit operation inventory for all shipped
clients: CLI, Python and TypeScript. Each exposes all six client operations;
there are no operation exclusions. Python's device flow is exposed by
`readlint.auth.login`, which handles polling and saved login rather than
returning raw device tokens. TypeScript exposes both low-level device calls.
Browser account/key management, browser approval, billing, health, deployment
and internal routes stay outside the exported client contract. MCP has not
shipped; its ticket must add its curated tools, intentional exclusions and
behavior tests to this inventory and job when it does.

The shared tests capture actual SDK methods and CLI parsing, then validate all
query/path/header inputs, all body fields, success/error response fixtures and
Python response types against the schema. The TypeScript generator runs in a
temporary directory and `diff` fails for stale checked-in types. Controlled
negative tests prove that a new operation, a new parameter/body field and stale
generated response types fail; reconciliation restores a passing run. The
transport suites separately exercise sanitized auth/validation failures,
transient responses, retry identity, terminal failures and redirects.

The TypeScript fetch transport, private credentials and package exports are
adapted from public `writeitai/mountable`
`d936589b1e200e347f03dfc32609c5d368668ae2` (`sdk/typescript/src/index.ts` and
package configuration). The regenerate/diff check follows `writeitai/fsit`
`6cf7db107b1d052f87824780f88a537470951a53`
(`web/openapi-ts.config.ts`, `web/scripts/check-openapi.ts`), reduced to the
public schema and TypeScript types. There is no generated runtime client or
runtime dependency. The generator's `js-yaml` transitive dependency is pinned
to patched 4.3.2 with an override.
