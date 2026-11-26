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
```

CI also installs each built wheel and source distribution in separate clean
virtual environments and runs `scripts/smoke.py` through the installed SDK and
CLI. Its local HTTP fixture checks device polling, saved credentials, a lost
submission response with one stored effect, CRUD, key precedence and errors.
The fixture never contacts readlint.com or a paid provider. CI covers Python
3.11 and 3.13 on Linux, and Python 3.13 on macOS. Saved login uses POSIX file
permissions; Windows users pass a key through the environment.

PR change detection uses `git diff --no-renames`. Only explicitly listed docs
paths skip Python checks. Unknown paths and workflow changes run everything.
Classifier failure runs the gated jobs. Main pushes and `workflow_dispatch`
always run all checks, builds and installed-package verifications. All jobs
use GitHub-hosted runners. No Docker or private source is needed.

## Release

1. Change the package version in a reviewed PR and update `uv.lock`.
2. Wait for main CI, then push the matching `vX.Y.Z` tag at the merged commit.
3. The release workflow checks that the tag belongs to main and matches
   `pyproject.toml`, runs tests, builds the wheel/source archive, verifies clean
   installs, and publishes both with SHA-256 checksums to a GitHub Release.
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

The stdio MCP adapter, `mcp.json` and draft-review skill are adapted from
`cmd/mountable/mcp.go`, `mcp.json` and `skills/mountable/SKILL.md` at the same
mountable revision. The Python MCP SDK owns the protocol; handlers reuse the
readlint SDK and sanitized errors. Four tools cover evaluation CRUD. The
serialized catalogue has a 6,000-byte CI budget in `tests/test_mcp.py`.
The installed-package smoke test uses MCP Python SDK 1.30.0 as a real stdio
client, discovers tools and exercises CRUD, saved/env/flag credentials,
invalid input, bad/missing credentials, lost-answer recovery and transient
failures against a controlled local HTTP service. It never calls a paid model.
