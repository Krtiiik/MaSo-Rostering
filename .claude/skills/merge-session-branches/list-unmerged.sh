#!/usr/bin/env bash
# Lists session branches (claude/*, and the older worktree-bridge-*) not yet
# merged into main, newest first. Other unmerged branches (backup/*,
# research/*) are not session work and are left out on purpose.
# Run from anywhere inside the repo.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

for b in $(git branch --list 'claude/*' 'worktree-bridge-*' --format='%(refname:short)'); do
  if ! git merge-base --is-ancestor "$b" main 2>/dev/null; then
    ts=$(git log -1 --format='%ct' "$b")
    echo "$ts $b"
  fi
done | sort -rn | while read -r ts branch; do
  echo "=== $branch ==="
  git log "main..$branch" --oneline
done
