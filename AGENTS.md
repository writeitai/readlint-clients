# readlint.com client repository

- Use readlint.com as the product name. Keep client implementations and shared
  client-side API and authentication logic here. Clients must install and work
  without access to the private product source.
- Build the simplest solution that meets the requirement. Use uv, Ruff and
  Pyright for Python. Follow the existing tooling and tests as clients are
  added.
- Read the relevant [shared project skills](.agents/skills) before changing
  project standards or writing public copy. Maintainers with access to the
  [private Autoboard source](https://github.com/writeitai/autoboard/tree/main/new-project-bootstrap/skills)
  refresh the bundle and record the source revision in the PR.
- Run local checks before opening a pull request. Use GitHub-hosted runners for
  every CI job. Merge all changes to main through pull requests.

## Public repository boundary

Keep backend code, production inventory, infrastructure identifiers, costs,
agreements, credentials and customer data out of this repository. Maintainers
apply the infra-inventory, business-ops and why-we-are-best skills in the
private product repository. Record infrastructure, business operations and
verified claims there.
