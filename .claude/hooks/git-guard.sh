#!/bin/sh
# PreToolUse hook for Bash and PowerShell: deny risky git operations.
# Usage: git-guard.sh <group>...   with groups from: publish rewrite skip discard remote nested
# Reads the tool-call JSON on stdin and matches the raw text (no jq needed), so it
# may also deny when a risky command merely appears in a description; that is fine.
# Exempt: a command with an explicit absolute `git -C <path>` strictly inside a temp folder (this
# covers the Claude scratchpad) or a Claude session worktree (.claude/worktrees/<name>/...), and
# `git worktree remove` of a path inside .claude/worktrees/. Plain commands in the current
# directory are never exempt. Keep the path helpers in sync with fs-guard.sh.

set -f
input=$(cat)
# Undo JSON escaping: \\ -> /, drop \", \n and \r -> ;, \t -> space.
body=$(printf '%s' "$input" | sed -e 's/\\\\/\//g' -e 's/\\"//g' -e 's/\\[nr]/;/g' -e 's/\\t/ /g')
git='(^|[^[:alnum:]_-])git(\.exe)?([[:space:]]+-[^[:space:]]+([[:space:]]+[^-[:space:]][^[:space:]]*)?)*[[:space:]]+'

# Normalise a path: forward slashes, no repeated or trailing slash, drive letter as /c/...
norm() {
  n=$(printf '%s' "$1" | tr '\\' '/' | tr -s '/')
  case $n in
    [A-Za-z]:|[A-Za-z]:/*) d=$(printf '%s' "$n" | cut -c1 | tr 'A-Z' 'a-z'); n=/$d${n#??} ;;
  esac
  case $n in ?*/) n=${n%/} ;; esac
  printf '%s' "$n"
}

# Fully resolved form of a path (symlinks and junctions followed); lexical when realpath is missing.
canon() {
  c=$(realpath -m -- "$1" 2>/dev/null) || c=$1
  norm "$c"
}

proj=$(norm "${CLAUDE_PROJECT_DIR:-}")
home=$(norm "${HOME:-}")

# Disposable roots. Temp: the usual folders plus TMPDIR/TEMP/TMP, unless one of those would contain
# the project or the home folder. Worktrees: <repo>/.claude/worktrees, found from the project folder
# (works from the main checkout and from inside a session worktree alike).
troots="/tmp
/var/tmp
/private/var/folders"
for v in "${TMPDIR:-}" "${TEMP:-}" "${TMP:-}"; do
  [ -n "$v" ] || continue
  r=$(norm "$v")
  case $r in /*/?*) ;; *) continue ;; esac
  case $proj in "$r"|"$r"/*) continue ;; esac
  case $home in "$r"|"$r"/*) continue ;; esac
  troots="$troots
$r"
done
wroots=""
if [ -n "$proj" ]; then
  case $proj in
    */.claude/worktrees/*) wr=${proj%%/.claude/worktrees/*}/.claude/worktrees ;;
    *) wr=$proj/.claude/worktrees ;;
  esac
  wroots="$wr"
fi
# Add the resolved form of every root, so /tmp -> /private/tmp style links still match.
for list in troots wroots; do
  eval "cur=\$$list"
  extra=""
  while IFS= read -r r; do
    [ -n "$r" ] || continue
    c=$(canon "$r")
    [ "$c" = "$r" ] || extra="$extra
$c"
  done <<EOF
$cur
EOF
  eval "$list=\"\$cur\$extra\""
done

# Is $1 strictly inside a root of list $2: depth 1 = root/<x>, depth 2 = root/<name>/<x>.
under() {
  while IFS= read -r r; do
    [ -n "$r" ] || continue
    case $3 in
      1) case $1 in "$r"/?*) return 0 ;; esac ;;
      2) case $1 in "$r"/?*/?*) return 0 ;; esac ;;
    esac
  done <<EOF
$2
EOF
  return 1
}

# Is $1 a literal absolute path strictly inside a temp folder or a Claude session worktree
# (mode $2 = wt: inside .claude/worktrees/ only)? No .., variables, %, backticks, braces or wildcards
# anywhere. Symlinks and junctions are resolved first, so a link cannot lead out.
allowed_path() {
  p=${1#\'}
  p=$(norm "${p%\'}")
  case $p in /?*) ;; *) return 1 ;; esac
  case $p in *..*|*\$*|*%*|*\`*|*[{}*?[]*) return 1 ;; esac
  cp=$(canon "$p")
  if [ "$2" = wt ]; then
    under "$cp" "$wroots" 1
  else
    under "$cp" "$troots" 1 || under "$cp" "$wroots" 2
  fi
}

# Does git invocation $1 carry only absolute, allowed -C paths, and at least one?
c_exempt() {
  set -- $1
  shift
  have=0
  while [ $# -gt 0 ]; do
    case $1 in
      -C) [ $# -ge 2 ] && allowed_path "$2" || return 1; have=1; shift 2 ;;
      -c|--exec-path|--namespace|--super-prefix|--config-env) shift 2 ;;
      -*) shift ;;
      *) break ;;
    esac
  done
  [ $have = 1 ]
}

# Is git invocation $1 a `worktree remove` of a path inside .claude/worktrees/?
wt_remove_ok() {
  set -- $1
  seen=0
  last=""
  for t in "$@"; do
    case $t in
      remove) seen=1 ;;
      -*) ;;
      *) [ $seen = 1 ] && last=$t ;;
    esac
  done
  [ -n "$last" ] && allowed_path "$last" wt
}

# One git invocation per line: from `git` up to the next ; & | or quote.
invocations=$(printf '%s\n' "$body" | grep -Eio '(^|[^[:alnum:]_-])git(\.exe)?[[:space:]][^|;&"]*' | sed -E 's/^[^[:alnum:]]*//')
groups="$*"
reason=""

hit() { printf '%s' "$1" | grep -Eq -e "$2"; }

# Sets reason when invocation $1 is risky for one of the groups and not exempt.
check() {
  line=$1
  for group in $groups; do
    case "$group" in
      publish)
        hit "$line" "${git}push\b" &&
          why="git push is visible to others (this includes force-pushes and tag pushes)" ;;
      rewrite)
        hit "$line" "${git}(reset[^|;&]*--hard|rebase|filter-branch|commit[^|;&]*--amend)" &&
          why="this rewrites git history" ;;
      skip)
        hit "$line" '--no-verify|--no-gpg-sign|commit\.gpgsign=false' &&
          why="this skips git hooks or commit signing" ;;
      discard)
        hit "$line" "${git}(clean\b|restore\b|stash[[:space:]]+(drop|clear)\b|branch[^|;&]*(-D\b|--delete[^|;&]*--force|--force[^|;&]*--delete)|checkout[^|;&]*([[:space:]]--[[:space:]]|[[:space:]]\.([[:space:];&|]|\$)))" &&
          why="this can discard uncommitted or unmerged work" ;;
      remote)
        hit "$line" "${git}(remote[[:space:]]+(add|set-url|remove|rm)\b|config[^|;&]*--(global|system)\b)" &&
          why="this changes remotes or global git configuration" ;;
      nested)
        if hit "$line" "${git}(submodule[[:space:]]+deinit|submodule[^|;&]*--force)"; then
          why="this can delete submodule content"
        elif hit "$line" "${git}worktree[[:space:]]+prune\b"; then
          why="this removes a worktree that Claude did not create"
        elif hit "$line" "${git}worktree[[:space:]]+remove\b"; then
          wt_remove_ok "$line" || why="this removes a worktree that Claude did not create"
        fi ;;
    esac
    if [ -n "$why" ]; then
      c_exempt "$line" || { reason=$why; return; }
      why=""
    fi
  done
}

why=""
while IFS= read -r line; do
  [ -n "$line" ] || continue
  check "$line"
  [ -n "$reason" ] && break
done <<EOF
$invocations
EOF

# --no-verify and friends count wherever they appear, so they are exempt only when every git
# invocation in the command carries an allowed -C.
if [ -z "$reason" ]; then
  case " $groups " in
    *" skip "*)
      if printf '%s' "$body" | grep -Eq -e '--no-verify|--no-gpg-sign|commit\.gpgsign=false'; then
        all=1
        [ -n "$invocations" ] || all=0
        while IFS= read -r line; do
          [ -n "$line" ] || continue
          c_exempt "$line" || all=0
        done <<EOF
$invocations
EOF
        [ $all = 1 ] || reason="this skips git hooks or commit signing"
      fi ;;
  esac
fi

if [ -n "$reason" ]; then
  msg="Blocked by the project git guardrails: $reason. Do not retry, rephrase or work around it (no aliases, git -c overrides or wrappers): tell the user what you wanted to do and why, and let them run it or decide. Allowed without prompting: a guarded command with an explicit absolute git -C path strictly inside a temp folder (/tmp, /var/tmp, the TEMP or TMPDIR folder, which includes the session scratchpad) or inside a Claude session worktree (${wr:-<repo>/.claude/worktrees}/<name>/...), and git worktree remove of a path inside ${wr:-<repo>/.claude/worktrees}. Plain commands in the current directory, relative -C paths, and paths with .., variables or wildcards get no exemption: use the literal absolute path. If the command only mentions the operation in text, for example in a commit message, reword it."
  printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"%s"}}\n' "$msg"
fi
exit 0
