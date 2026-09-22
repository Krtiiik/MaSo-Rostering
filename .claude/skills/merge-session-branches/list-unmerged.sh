#!/usr/bin/env bash
# Lists worktree-bridge-* branches not yet merged into main, newest first.
# Run from anywhere inside the repo. Verified this session against a repo
# with 10-15 concurrent worktree-bridge-* branches.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

for b in $(git branch --list 'worktree-bridge-*' --format='%(refname:short)'); do
  if ! git merge-base --is-ancestor "$b" main 2>/dev/null; then
    ts=$(git log -1 --format='%ct' "$b")
    echo "$ts $b"
  fi
done | sort -rn | while read -r ts branch; do
  echo "=== $branch ==="
  git log "main..$branch" --oneline
done
