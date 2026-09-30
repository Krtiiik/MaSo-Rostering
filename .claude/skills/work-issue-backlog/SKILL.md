---
name: work-issue-backlog
description: Autonomously work through this repo's GitHub issue backlog (Krtiiik/MaSo-Rostering) one ready ticket at a time — claim it, have the issue-implementer agent build it in a worktree, merge into main, run pytest, push, close the issue (and its spec once every ticket is done) — until nothing is ready, then write a summary. Use when asked to "work the backlog", "burn down the issues", "implement the ready tickets", "keep going through the issues while I'm away", or any unattended run over several GitHub issues. Not for implementing one named issue interactively.
---

# Work the issue backlog

An unattended loop: the user is away and will read only the final summary.
Never stop to ask. Wherever you would normally ask, take the **conservative**
choice (the one that is easiest to undo, or doing nothing) and record it for
the summary. Keep going until no ticket is ready.

## What this run may and may not do

The invocation of this skill is the user's authorization for exactly this:

- May: commit; merge into local `main`; push `main` to `origin` after each
  green merge; comment on, assign/unassign, and close issues in
  `Krtiiik/MaSo-Rostering`.
- May not: create or push tags, cut releases, bump versions, force-push,
  rewrite history (`reset --hard` of *pushed* commits, rebase of `main`,
  amend), or delete branches/worktrees that might still hold work.
- The `data/` folder holds real people's survey data. Use it at most for a
  one-off manual smoke check; never modify it, commit it, or build tests or
  fixtures from it. Tell the implementer the same.

If the user's prompt narrows or widens any of this, their prompt wins.

## Setup (once per run)

1. Read `docs/agents/issue-tracker.md` (gh conventions, race-safe edits,
   blocking) and `CONTEXT.md`.
2. Make sure `.claude/agents/issue-implementer.md` exists on `main` and is
   committed. It already does in this repo; if it's missing, recreate it
   (frontmatter `model: sonnet`, `effort: high`; body: implement exactly one
   issue, read `CONTEXT.md` + `.claude/CLAUDE.md` first, test-first with the
   `mattpocock-skills:tdd` skill, `CHANGELOG.md` entry under
   `## [Unreleased]` for user-facing changes, full pytest suite green,
   rebuild the grid bundle if `components/rostering-assignment-grid/`
   changed, Conventional Commit referencing the issue, never merge/push/touch
   issues, never use `data/`, stop and report instead of guessing or doing
   anything irreversible) and commit it as
   `chore: add issue-implementer agent definition`.
3. `git status` must be clean on `main` and `main` in sync with `origin/main`
   (`git fetch` then compare). If it isn't, don't try to fix it: stop and put
   it in the summary. Starting on a dirty tree makes every later "undo the
   merge" unsafe.
4. Keep a running notes list (closed / skipped / conservative choices) in
   your context; it becomes the summary.

Python is the project venv: `E:\Code\.venvs\rostering\Scripts\python.exe`.

## The loop (strictly one ticket at a time)

### 1. Pick

```bash
python .claude/skills/work-issue-backlog/backlog.py ready --skip <n> <n> ...
```

Pass every issue skipped earlier in this run. The script prints each open
issue's status and a final `NEXT: <n>` (lowest-numbered ready ticket) or
`NEXT: none`. "Ready" means open, not a spec/map/parent, no assignee, no open
blocker. Blockers are both GitHub's native dependencies and the refs under
the body's `## Blocked by` heading; the parent spec is the link under
`## Parent`. Those body sections are how this repo actually records
structure, so trust the script over `gh issue list` alone.

If `NEXT: none`, go to the summary.

Issues already assigned (even to the user) are not ready. An assignment to
the user can be left over from an interrupted earlier run. Don't reclaim it
or remove the assignee; list it in the summary instead, since you can't tell
whether a person is working on it.

### 2. Claim

Follow the race-safe edit rule: read `updated_at`, check that the issue is
still unassigned, re-read `updated_at` right before writing, then
`gh issue edit <n> --add-assignee @me`. If someone else claimed it in the
meantime, drop it and pick again.

### 3. Implement

Fetch the full text (`gh issue view <n> --comments`), then spawn the
`issue-implementer` agent with `isolation: "worktree"` and
`run_in_background: false`. You need its result before anything else can
happen, and parallel tickets would conflict on `main`. The prompt should
include the issue number, title, full body and comments, the parent spec's
number, and a reminder not to use `data/`.

Read its final report. It bailed if it says it stopped or made no commit, or
if its branch has no commits beyond `main`
(`git log main..<branch> --oneline`). If so, go to step 6.

### 4. Merge

From the primary checkout on `main`, note `PRE=$(git rev-parse HEAD)`, then
`git merge --no-ff <branch> -m "Merge branch '<branch>' into main (#<n>)"`.
The `merge-session-branches` skill covers conflict resolution (including
semantic conflicts between diverged Streamlit/frontend features) and the
bundle rebuild; load it when there are conflicts or frontend changes. Its
branch-listing script looks for `worktree-bridge-*`, while implementer
branches are named `worktree-agent-*`, so use its merge guidance, not its
branch discovery.

- If the merge touched `components/rostering-assignment-grid/` (or resolved
  conflicts there), rebuild the checked-in bundle (`npm run build` in
  `components/rostering-assignment-grid/rostering_assignment_grid/frontend`)
  and commit the rebuilt bundle if it changed.
- Run the full suite on `main`: `E:\Code\.venvs\rostering\Scripts\python.exe -m pytest -q`.

Resolve conflicts only when the right answer is clear from both sides'
intent. If a conflict needs a product decision, treat it as a failure
(step 6). Guessing on `main` is worse than skipping a ticket.

### 5. Green: push and close

1. `git push origin main`. If the push is rejected because origin moved,
   `git pull --no-rebase` (a merge, not a rebase), re-run pytest, and push
   again. Never force.
2. Close the ticket with a comment giving the merge commit hash and a 1–3
   line summary of what was delivered:
   `gh issue close <n> --comment "Merged in <hash>. <summary>"`.
3. Check the parent spec:
   `python .claude/skills/work-issue-backlog/backlog.py spec-status <spec>`.
   On `ALL_CLOSED: yes`, close the spec with a comment listing the delivered
   tickets (`#n title`). If the spec itself is under a Map, leave the Map
   alone; closing Maps is out of scope for this run.
4. Any body edit (for example, ticking a task list in a spec) follows the
   race-safe rule in `docs/agents/issue-tracker.md`. Don't edit bodies you
   don't need to.

Then go back to step 1.

### 6. Failure: undo, report, skip

Covers an implementer that bailed, a merge you couldn't resolve, a failed
bundle build, and red tests.

1. Get `main` back to green without rewriting anything pushed:
   - Merge in progress: `git merge --abort`.
   - Merge committed but **not pushed** (always the case here, since you
     push only after green): `git reset --hard $PRE` is allowed, because
     it only discards the local merge you just made. First check
     `git rev-parse origin/main` against `PRE`'s ancestry so you are sure
     nothing you drop was pushed.
   - Anything already pushed: `git revert -m 1 <merge>` and push. Never
     reset.
   Re-run pytest to confirm `main` is green again.
2. Leave the implementer's branch and worktree in place. They are the
   evidence and the user may want to finish the work.
3. Comment on the issue: what went wrong (bail reason, conflicting files,
   failing test names and a short error excerpt), and the branch name.
4. Remove your assignee (race-safe), leave the issue open, add it to the
   skip list. Anything it blocks stays unready this run, which is intended.

Then go back to step 1.

## Final summary

Reply to the user in this shape (keep each line short):

```
## Backlog run summary

**Closed tickets**
- #n Title: <merge hash>

**Closed specs**
- #n Title (tickets: #a, #b)

**Skipped** (left open, unassigned)
- #n Title: <reason>; branch <name>

**Still blocked**
- #n Title: blocked by #a (skipped/open), #b

**Not touched**
- #n Title: assigned to <login> before this run

**Conservative choices made**
- <what you'd have asked, and what you did instead>

**main**: <short hash> <subject>, pushed: yes/no, pytest: <passed/failed counts>
```

Also mention in one line if `[Unreleased]` in `CHANGELOG.md` now looks
release-worthy, but don't bump or tag anything.
