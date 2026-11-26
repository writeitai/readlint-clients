#!/usr/bin/env bash
set -euo pipefail
python=true
typescript=true
contract=true
if [[ "${GITHUB_EVENT_NAME:-}" == pull_request ]]; then
  files=$(git diff --no-renames --name-only "$BASE_SHA" "$HEAD_SHA")
  python=false
  typescript=false
  contract=false
  while IFS= read -r file; do
    case "$file" in
      README.md|AGENTS.md|LICENSE|docs/*|.agents/*|skills-lock.json|sdk/typescript/README.md|sdk/typescript/LICENSE|'') ;;
      src/*|tests/*|pyproject.toml|uv.lock|scripts/smoke.py) python=true; contract=true ;;
      sdk/typescript/*) typescript=true; contract=true ;;
      contracts/fixtures.json) typescript=true; contract=true ;;
      contracts/*|scripts/check_contract.py) contract=true ;;
      *) python=true; typescript=true; contract=true ;;
    esac
  done <<< "$files"
fi
printf 'python=%s\ntypescript=%s\ncontract=%s\n' "$python" "$typescript" "$contract" >> "$GITHUB_OUTPUT"
