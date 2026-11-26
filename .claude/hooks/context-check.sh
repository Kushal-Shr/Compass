#!/usr/bin/env bash
# Stop hook: if tracked project files changed since the last check but
# CONTEXT.md did not, send Claude back once to update it.
# Git-ignored files (plan/, .env, ...) are not counted.
set -euo pipefail

input=$(cat)
cd "${CLAUDE_PROJECT_DIR:-.}"
git rev-parse --git-dir >/dev/null 2>&1 || exit 0

state="$(git rev-parse --git-dir)/compass-context-hook.state"

tree_hash=$({
  git diff HEAD -- . ':(exclude)CONTEXT.md' 2>/dev/null
  git ls-files -o --exclude-standard -- . ':(exclude)CONTEXT.md' | while IFS= read -r f; do
    printf '%s\n' "$f"; cat -- "$f" 2>/dev/null
  done
} | shasum | cut -d' ' -f1)
ctx_hash=$( (cat CONTEXT.md 2>/dev/null || true) | shasum | cut -d' ' -f1)

prev_tree=""; prev_ctx=""
[ -f "$state" ] && read -r prev_tree prev_ctx < "$state" || true
printf '%s %s\n' "$tree_hash" "$ctx_hash" > "$state"

# Already sent back once this turn, or first run: never block (no loops).
[ "$(printf '%s' "$input" | jq -r '.stop_hook_active // false')" = "true" ] && exit 0
[ -z "$prev_tree" ] && exit 0

if [ "$tree_hash" != "$prev_tree" ] && [ "$ctx_hash" = "$prev_ctx" ]; then
  jq -n '{decision: "block", reason: "Project files changed this turn but CONTEXT.md did not. Update CONTEXT.md (Status, file map, decisions, known issues or open questions) if any of that changed. If nothing it tracks changed, say so in one line and stop."}'
fi
exit 0
