---
name: merge-session-branches
description: Merge unmerged worktree-bridge-* session branches into main, resolve conflicts (including semantic conflicts between diverged Streamlit/frontend features), rebuild the assignment-grid frontend bundle, and verify with pytest. Use when asked to "merge the session/worktree branch(es)", "merge the latest branch/session", or "merge <feature-name> into main".
---

# Merge session branches

Each Claude Code worktree-bridge session works on its own
`worktree-bridge-cse_*` branch in `.claude/worktrees/<name>/`. This skill
merges that work into `main` from the primary checkout. Verified this
session across ~10 merges, including two with real multi-file conflicts.

## 1. Find candidate branches

```bash
.claude/skills/merge-session-branches/list-unmerged.sh
```

Lists every `worktree-bridge-*` branch not yet an ancestor of `main`,
newest-commit-first, with each branch's not-yet-merged commits. Use this to:

- Find "the latest branch/session" (top of the list).
- Find a branch by feature name/session description (grep the commit
  subjects, or match against the description the user gave — session names
  like "Excel roster export styling" map to commit subjects like `feat:
  match Excel roster export to historical roster layout`, not to the opaque
  `cse_...` branch id).

If a target branch has *more* commits than last time you looked, that
session kept working — merge again to pick up the new commits (branches get
re-merged repeatedly across a working session).

Before touching a **locked** worktree (`git worktree list` shows `locked`)
or removing anything, check `ListAgents` for a live peer session still
attached to it — this skill only merges branches, it never deletes
worktrees or touches sessions that might still be using them.

## 2. Merge

```bash
git merge <branch> --no-edit -m "$(cat <<'EOF'
Merge branch '<branch>' into main

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

Three outcomes:

- **Fast-forward / clean merge** — done, skip to step 4.
- **Conflicts, all in generated build artifacts** — skip to step 3.
- **Conflicts in source** — read on.

## 3. Resolve conflicts

### Build artifacts: never hand-merge, always rebuild

`components/rostering-assignment-grid/rostering_assignment_grid/frontend/build/index-*.js`
and `index-_hash_.css` are compiled output with a content hash in the
filename. A conflict here (often `rename/delete` or `modify/delete`, since
the hash changes every build) is noise, not a real conflict:

```bash
git rm -f components/rostering-assignment-grid/rostering_assignment_grid/frontend/build/index-*.js
# if index-_hash_.css itself conflicts, either side is fine — it's overwritten next:
git checkout --theirs components/rostering-assignment-grid/rostering_assignment_grid/frontend/build/index-_hash_.css 2>/dev/null || true
```

Rebuild after resolving *source* conflicts (step below), not before.

### CHANGELOG.md

Always a union merge: keep every bullet from both sides under its existing
`### Added`/`### Changed`/`### Fixed` heading. Watch for the incoming
branch re-describing a feature that a *different*, already-merged branch
also implemented (see next section) — if so, drop the incoming branch's
now-redundant/duplicate bullet and keep only its genuinely new content.

### Source conflicts: check which side is stale before merging text

The most common real conflict shape in this repo: two `worktree-bridge-*`
branches forked from the same commit, and **one landed on `main` first**.
The second branch's diff was computed against the *old* common ancestor, so
its conflict hunk may contain logic that a *third*, already-merged commit
has since replaced entirely (e.g. a prop/function/whole code path renamed
or restructured). Blindly keeping "both sides" text-unions a conflict like
that produces code that references now-deleted variables and fails
typecheck/tests.

Before resolving each hunk:

1. `git show <branch>:<path>` to see that branch's *whole* file, not just
   the diff — understand what it was trying to do in isolation.
2. `git show HEAD:<path>` (or just read current disk state) to see what's
   already there — check whether HEAD's version already supersedes part of
   what the incoming branch touches (same feature, done differently or more
   completely, after a later refactor).
3. Resolve semantically: keep the newer/superseding logic, port over only
   the incoming branch's *genuinely new* contribution on top of it. Don't
   default to "keep both" without checking for this.
4. Remove anything that becomes unused as a result (dead imports, unused
   props/params) rather than leaving it as dead weight.

## 4. Rebuild the frontend (only if frontend/*.ts, *.tsx, or *.css changed)

```bash
cd components/rostering-assignment-grid/rostering_assignment_grid/frontend
npm install   # only needed if package.json changed
npm run build # runs clean -> tsc --noEmit -> vite build
```

A clean typecheck + build here is strong evidence the semantic merge in
step 3 was correct — a dangling reference to a removed prop/variable fails
`tsc --noEmit` immediately. Stage the newly-hashed `build/index-*` files
and `git rm` any old ones that vanished (`git status` shows old as deleted,
new as untracked).

## 5. Verify and commit

```bash
"E:/Code/.venvs/rostering/Scripts/pytest.exe" -q
```

All tests must pass before committing (see the venv path in project
memory if this path is stale). Then:

```bash
git add <every file touched above>
git commit --no-edit   # or -m with a summary if you resolved real conflicts —
                        # note what was semantically dropped/superseded and why
git status --short     # must be clean
```

Do not push to origin unless explicitly asked (see global git-commit
conventions in CLAUDE.md).

## Gotchas encountered this session

- `git merge --no-edit -m "..."` on a **fast-forward-eligible** merge
  silently ignores `-m` and fast-forwards with no merge commit — that's
  expected, not an error.
- A branch's own `_overlay_sheet`/`structural_row_start`-style helper
  function can be entirely dead code after a merge, if a later commit
  already reworked that whole feature under different names — grep for the
  old names post-merge to confirm nothing still calls them.
- Windows long paths: `git worktree remove` can fail with "Filename too
  long" on deeply nested `node_modules`-style paths (unrelated to this
  skill's merges, but if cleaning up a worktree afterward, use PowerShell
  `Remove-Item -LiteralPath "\\?\<path>" -Recurse -Force` as a fallback).
