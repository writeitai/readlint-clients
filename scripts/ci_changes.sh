#!/usr/bin/env bash
set -euo pipefail
run=true
if [[ "${GITHUB_EVENT_NAME:-}" == pull_request ]]; then
  files=$(git diff --no-renames --name-only "$BASE_SHA" "$HEAD_SHA")
  run=false
  while IFS= read -r file; do
    case "$file" in
      README.md|AGENTS.md|LICENSE|docs/*|.agents/*|skills-lock.json|'') ;;
      *) run=true ;;
    esac
  done <<< "$files"
fi
printf 'python=%s\n' "$run" >> "$GITHUB_OUTPUT"
