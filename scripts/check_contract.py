"""Compare the committed public schema to a supplied export or the hosted export.

No private source or credentials are needed. CI always checks the hosted copy;
--schema also accepts the backend's client artifact for pre-deploy checks.
"""

import argparse
import json
from pathlib import Path
from urllib.request import HTTPRedirectHandler, HTTPSHandler, build_opener

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "contracts" / "openapi.json"
CLIENTS = ROOT / "contracts" / "clients.json"


def operations(schema):
    return {
        f"{method.upper()} {path}"
        for path, methods in schema["paths"].items()
        for method in methods
        if method in {"get", "post", "put", "patch", "delete", "head", "options"}
    }


def check_coverage(schema):
    clients = json.loads(CLIENTS.read_text())
    assert set(clients) == {"python", "cli", "typescript"}, (
        "Review every shipped client"
    )
    for name, coverage in clients.items():
        assert set(coverage) == operations(schema), f"{name}: stale operation coverage"
        assert all(coverage.values()), f"{name}: unnamed client entry point"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema", type=Path, help="Fresh backend --client export")
    args = parser.parse_args()
    committed = json.loads(SCHEMA.read_text())
    if args.schema:
        fresh = json.loads(args.schema.read_text())
    else:
        opener = build_opener(HTTPSHandler(), NoRedirect())
        with opener.open(
            "https://readlint.com/v1/openapi.json", timeout=30
        ) as response:
            body = response.read(2_000_001)
        if len(body) > 2_000_000:
            raise SystemExit("Unexpectedly large client schema")
        fresh = json.loads(body)
    check_coverage(fresh)
    if fresh != committed:
        raise SystemExit(
            "Client OpenAPI drift: update contracts/openapi.json from the backend "
            "--client export, regenerate TypeScript types, reconcile every client "
            "and run the contract tests. See docs/development.md."
        )
    print(
        f"Public schema matches; {len(operations(fresh))} operations covered by every shipped client."
    )


if __name__ == "__main__":
    main()
