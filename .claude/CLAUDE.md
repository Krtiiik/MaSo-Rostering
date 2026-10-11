# Rostering

This project assigns registered helpers ("pomocníci") to buildings, rooms, and
roles for a Czech math competition ("MaSo"/"MaSe"), based on their preferences,
using an OR-Tools CP-SAT solver. The web app's front end is in Czech (every
user-facing string is written in Czech; see "Language" in `CONTEXT.md`), while code,
identifiers and developer docs stay English.

## Project documentation

Docs for Claude, kept in the repository:

- @CONTEXT.md: glossary of the project's terms and top-level concepts (Season, Helper, Organizer, Building, Room, Role, Manual roles, ...) and the Czech front-end rules. Use these terms exactly in code, commits and conversation.
- `ARCHITECTURE.md`: the big picture (components, how they relate, data flow), the reasons behind design choices, and the detailed implementation notes and decisions log (ingestion rules, dark mode, data pipeline, known data quirks, per-feature status). Read it before changing structure or adding a component, and when a design looks odd.

Maintaining them:

- Record only what the source can't tell you: intent, vocabulary, rationale and non-obvious relationships. Don't list files, signatures or anything a quick search would find.
- Update a doc in the same change that makes it stale or introduces something worth recording (a new term, a design choice and its reason, a convention). Don't wait to be asked and don't batch it for later.
- Keep entries short. When a doc and the code disagree, trust the code and fix the doc.
- A new term goes in `CONTEXT.md` as a short definition; its detailed rules and a feature's implementation notes go in `ARCHITECTURE.md` ("Domain behaviour in detail", "Implementation notes"), not in this file.

## Committing

- Commit proactively when a logical chunk of work is done, without waiting to be asked each time. Never push unless asked.
- Split large work into several commits, one per logical change, each leaving the project in a working state. Do not squash unrelated changes into one commit.

## Git commits

- Summary line: use Conventional Commits prefixes (`feat:`, `fix:`, `docs:`, `refactor:`, `chore:`, `test:`, ...) followed by a short imperative description, e.g. `feat: add team distribution solver`.
- Commit scopes: add a parenthesised scope after the type, e.g. `fix(parser): handle empty input`, only when the change is confined to one identifiable area (a module, package, or top-level folder) and the name is not obvious from the description. Omit it for cross-cutting changes. Reuse scope names already in the history rather than inventing variants.
- Avoid vague messages ("fix stuff", "update files"); the summary should say what changed.
- Add a body (after a blank line) only when the reason for the change is not obvious from the summary. Explain why, not what; the diff shows what.

## Changelog and versioning

- Use Semantic Versioning (semver.org) with MAJOR.MINOR.PATCH version numbers.
- Maintain `CHANGELOG.md` in the Keep a Changelog format (keepachangelog.com).
- Log every user-facing change (feature, fix, behavior change) under an `## [Unreleased]` section at the top, added in the same commit as the change itself, not batched later.
- Never bump the version on your own initiative. Only when explicitly asked for a release or version bump, move `[Unreleased]` under a new `## [X.Y.Z] - YYYY-MM-DD` heading, bump `version` in `pyproject.toml` to match, and tag the commit (`git tag -a vX.Y.Z -m "vX.Y.Z"`). You may mention in one line that something looks release-worthy, but don't act on it.
- Pushing a `v*.*.*` tag triggers `.github/workflows/build-executables.yml`, which builds and attaches that release's Windows/Linux/macOS executables — so cutting a release means pushing the tag, not just creating it locally.

## Testing

- When a test fails, fix the code. Change a test only when it is wrong or the requested behaviour changed, and say so. Never skip, delete or loosen a test to get it passing.
- Reproduce a bug with a failing test before fixing it, and keep that test.
- Ship tests with new or changed behaviour in the same change.
- Follow the project's existing test framework, layout, naming and helpers; do not introduce another framework or assertion library.

## Test commands

- Tests use pytest (pytest-asyncio, `asyncio_mode = "auto"`) in a flat `tests/` folder, one `test_<feature>.py` per feature; shared helpers are in `tests/survey_factory.py` and `tests/tag_rules.py`; the web app tests drive NiceGUI's async user simulation.
- All tests: `python -m pytest -q` with the project venv active (about 90 s, so give it a long timeout).
- Tests for a change: run the `tests/test_<feature>.py` file(s) for the area touched (e.g. `test_tags.py`, `test_forced_friends*.py`), then the full suite before finishing.
- Single test: `python -m pytest tests/<file>.py::<test_name> -q` (a whole file: `python -m pytest tests/<file>.py -q`; by keyword: `-k <expr>`).

## Issue handling

- Read issues (list, view) freely whenever they help you understand the task.
- Creating, commenting on, editing, closing or reopening an issue notifies other people. Do it only when the user explicitly asked for that action; otherwise ask first with AskUserQuestion.

## Issue tracking

- Issues live on GitHub, through the `gh` CLI. Read `ISSUE-TRACKING.md` for the commands before your first use.
- When a `gh` command fails on authentication, report the error and let the user log in.

## Git guardrails

This project has git guardrails: certain dangerous git operations are blocked automatically, without a prompt. They are enforced by a `PreToolUse` hook (`.claude/hooks/git-guard.sh`, registered in the project's Claude settings) on both the Bash and PowerShell tools. The guarded groups are:

- **Rewriting history**: `git reset --hard`, `git rebase`, `git commit --amend`, `git filter-branch`.
- **Skipping safeguards**: `--no-verify`, `--no-gpg-sign`, and `commit.gpgsign=false`.

**Allowed without prompting.** Work with these directly and don't treat a block as a reason to retry in another form:

- A guarded command that carries an explicit absolute `git -C <path>` strictly inside a temp folder (`/tmp`, `/var/tmp`, the folder in `TMPDIR`, `TEMP`, or `TMP`, which includes the session scratchpad) or inside a Claude session worktree (`<repo>/.claude/worktrees/<name>/...`). Use this for scratch repositories, e.g. `git -C /tmp/demo clean -fd`.
- `git worktree remove` of a path inside `<repo>/.claude/worktrees/`.

The hook checks the literal path in the command, so it can't be tricked and neither should you try:

- Write the full absolute path. A plain command in the current directory, a relative `-C`, `~`, variables (`$TMPDIR`, `$env:TEMP`), braces, a `..` or a wildcard in the path are never exempt, even when the current directory is itself a session worktree.
- Symlinks and junctions are resolved first; a link inside temp that points elsewhere is not exempt.
- Every git command in the line needs its own allowed `-C`; one plain `git push` after an exempt command still blocks.

- The user chose these guardrails deliberately. Do not avoid them: no rephrased or equivalent commands, aliases, `git -c` overrides, scripts or wrappers, other tools that call git, and no editing of the settings, the hook, or this file to switch them off.
- When a guardrail blocks something, say what the operation would have done and why you wanted it, then wait for the user. They may run it themselves or give new instructions. If they decline, do not run it or an equivalent.
- The hook matches raw command text, so a command that only mentions a guarded operation (in a commit message, say) can be blocked too; reword it.
- In a sub-session or agent, finish the rest of the task and report the blocked operation to the parent session or the user.

## Filesystem guardrails

This project has filesystem guardrails: certain dangerous or irreversible filesystem operations are blocked automatically, without a prompt. They are enforced by a `PreToolUse` hook (`.claude/hooks/fs-guard.sh`, registered in the project's Claude settings) on both the Bash and PowerShell tools. The guarded groups are:

- **Deleting**: `rm`, `rmdir`, `unlink`, `shred`, `find -delete`, and in PowerShell `Remove-Item`, `del`, and `rd`.
- **Disk-level**: `dd`, `mkfs`, `fdisk`, `parted`, `wipefs`, and in Windows `format` and `diskpart` (including `Format-Volume` and `Clear-Disk`).
- **Outside the project**: deleting, moving, or changing permissions of anything outside the project folder: absolute paths, `~`, `$HOME`, drive roots, and `..` (for example `rm -rf ~`).

**Allowed without prompting.** These targets are exempt from every group above except Disk-level, so work with them directly and don't treat a block as a reason to retry in another form:

- Anything strictly inside a temp folder: `/tmp`, `/var/tmp`, the folder in `TMPDIR`, `TEMP`, or `TMP` (on Windows `%LOCALAPPDATA%\Temp`). The session scratchpad lives there, so it is covered. The temp folder itself is not.
- Anything strictly inside a Claude session worktree: `<repo>/.claude/worktrees/<name>/...`. The worktree folder itself and `<name>/*` are not.
- For deletes only, relative build or dependency output: `node_modules`, `bin`, `obj`, `dist`, `build`, `target`, `out`, `coverage`, `.next`, `.cache`, `.venv`, `__pycache__`, and similar.

The hook checks the literal path in the command, so it can't be tricked and neither should you try:

- Write the full absolute path (for example the scratchpad path from the system prompt). Relative paths into temp or worktrees, `~`, variables (`$TMPDIR`, `$env:TEMP`, `%TEMP%`), and braces are not exempt.
- A `..` anywhere in the path, or a wildcard in a folder part, is never exempt. A wildcard in the last part is fine only below the exempt folder (`/tmp/x/*`, not `/tmp/*`).
- Symlinks and junctions are resolved first; a link inside temp that points elsewhere is not exempt.
- A command that changes directory first (`cd`, `pushd`, `Set-Location`) gets no relative exemption: use absolute paths instead of `cd x && rm -rf build`.
- Every target of a command must be exempt; one outside target blocks the whole command.

- The user chose these guardrails deliberately. Do not avoid them: no rephrased or equivalent commands, aliases, scripts or wrappers, other tools or languages that touch the same files (`python -c`, `xargs`, `robocopy`, ...), and no editing of the settings, the hook, or this file to switch them off.
- When a guardrail blocks something, say what the operation would have done and why you wanted it, then wait for the user. They may run it themselves or give new instructions. If they decline, do not run it or an equivalent.
- The hook matches raw command text, so a command that only mentions a guarded operation (in a commit message, say) can be blocked too; reword it.
- In a sub-session or agent, finish the rest of the task and report the blocked operation to the parent session or the user.
