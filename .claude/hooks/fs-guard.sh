#!/bin/sh
# PreToolUse hook for Bash and PowerShell: deny risky filesystem operations.
# Usage: fs-guard.sh <group>...   with groups from: delete move perms disk outside
# Reads the tool-call JSON on stdin and matches the raw text (no jq needed), so it
# may also deny when a risky command merely appears in a description; that is fine.
# Disposable targets are allowed: literal absolute paths strictly inside a temp folder
# (this covers the Claude scratchpad) or a Claude session worktree
# (.claude/worktrees/<name>/...), and, for deletes, relative build or dependency output.
# Anything it cannot parse with confidence is denied. Keep the path helpers in sync
# with git-guard.sh.

set -f
input=$(cat)
# Undo JSON escaping: \\ -> /, drop \", \n and \r -> ;, \t -> space. Then hide package-manager
# and git "rm"/"remove" subcommands, which are not filesystem deletes.
body=$(printf '%s' "$input" | sed -e 's/\\\\/\//g' -e 's/\\"//g' -e 's/\\[nr]/;/g' -e 's/\\t/ /g' \
  -E -e 's/(^|[^[:alnum:]_.-])(git|npm|pnpm|yarn|docker|podman|dotnet|pip|winget|choco|scoop|brew|nuget)[[:space:]]+(rm|remove|del|uninstall)([[:space:]]|$)/\1\2 _ /g')
start='(^|[^[:alnum:]_.-])'
sp='[[:space:]]+'

hit() { printf '%s' "$body" | grep -Eiq -e "$1"; }

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

# Is $1 a literal absolute path strictly inside a temp folder or a Claude session worktree?
# No .., variables, %, backticks or braces anywhere; wildcards only in the last component, and then
# only below the root. Symlinks and junctions are resolved first, so a link cannot lead out.
allowed_path() {
  p=${1#\'}
  p=$(norm "${p%\'}")
  case $p in /?*) ;; *) return 1 ;; esac
  case $p in *..*|*\$*|*%*|*\`*|*[{}]*) return 1 ;; esac
  dir=${p%/*}
  case $dir in *[*?[]*) return 1 ;; esac
  case ${p##*/} in
    *[*?[]*) cp=$(canon "$dir") ;;
    *) cp=$(canon "$p") ;;
  esac
  under "$cp" "$troots" 1 || under "$cp" "$wroots" 2
}

has_cd=""
hit "${start}(cd|chdir|pushd|popd|push-location|set-location|sl)${sp}" && has_cd=1

# Relative path inside build or dependency output? Not when the command changes directory first.
build_output() {
  t=$1
  if [ -n "$proj" ]; then
    p=$(norm "$t")
    case $p in "$proj"/*) t=${p#"$proj"/} ;; esac
  fi
  case $t in *..*) return 1 ;; /*|~*|\$*|%*|[A-Za-z]:*) return 1 ;; esac
  [ -z "$has_cd" ] || return 1
  for dir in node_modules bin obj dist build target out coverage .next .nuxt .svelte-kit .turbo .parcel-cache \
    .cache .gradle .venv .tox .mypy_cache .ruff_cache .pytest_cache __pycache__; do
    case $t in "$dir"|"$dir"/*|*/"$dir"|*/"$dir"/*) return 0 ;; esac
  done
  return 1
}

# Does $1 point outside the project folder (absolute, home, drive, or parent-relative)?
is_outside() {
  p=$(norm "$1")
  if [ -n "$proj" ]; then
    case $p in "$proj"|"$proj"/*) return 1 ;; esac
  fi
  case $p in
    /*|~*|\$HOME*|\$\{HOME*|\$USERPROFILE*|\$env:*|%*|..|../*|*/../*|*/..) return 0 ;;
  esac
  return 1
}

# Is target $1 fine for operation kind $2 (delete also accepts build output)?
exempt() {
  allowed_path "$1" && return 0
  [ "$2" = delete ] && build_output "$1" && return 0
  return 1
}

# Command segments for the verbs in $1 (alternation): verb plus arguments up to the next ; & | or quote.
segments() { printf '%s\n' "$body" | grep -Eio -e "${start}($1)${sp}[^|;&\"]*" | sed -E 's/^[^[:alnum:]]*//'; }

# Segments on stdin, kind in $1. Prints x if any target is not exempt (kind outside: is outside the
# project and not exempt), or if a segment has no target that can be found (not for outside).
risky_segments() {
  kind=$1
  while IFS= read -r seg; do
    [ -n "$seg" ] || continue
    set -- $(printf '%s' "$seg" | tr -s '/ ' | tr ',' ' ')
    verb=$(printf '%s' "$1" | tr 'A-Z' 'a-z')
    shift
    skip=0; max=0; lastonly=0; tflag=0; pend=0; n=0; found=0; list=""; last=""
    case $verb in
      chmod|chown|chgrp) skip=1 ;;
      set-content|add-content|out-file|clear-content|clc|ac) max=1 ;;
      cp|copy|copy-item|cpi|xcopy) lastonly=1 ;;
    esac
    for t in "$@"; do
      if [ $pend = 1 ]; then pend=0; continue; fi
      if [ "$verb" = find ]; then
        case $t in -*|\(*|\!*) break ;; esac
      fi
      case $t in
        -*)
          case $(printf '%s' "$t" | tr 'A-Z' 'a-z') in
            -value|-encoding|-inputobject|-filter|-include|-exclude|-stream|-width|-erroraction|-ea|-errorvariable|-ev|-newname|-credential|-itemtype|-aclobject) pend=1 ;;
          esac
          case $t in *[tT]*) tflag=1 ;; esac
          continue ;;
        \>*|[0-9]\>*|/dev/null|\$null|nul) continue ;;
      esac
      t=${t#\'}
      t=${t%\'}
      [ -n "$t" ] || continue
      n=$((n + 1))
      [ $n -gt $skip ] || continue
      if [ $max -gt 0 ] && [ $((n - skip)) -gt $max ]; then continue; fi
      found=1
      last=$t
      list="$list
$t"
    done
    if [ $found = 0 ]; then
      [ "$kind" = outside ] && continue
      echo x
      return
    fi
    # cp writes only its last operand, unless an option like -t may redirect it.
    if [ $lastonly = 1 ] && [ $tflag = 0 ]; then list=$last; fi
    while IFS= read -r t; do
      [ -n "$t" ] || continue
      if [ "$kind" = outside ]; then
        if is_outside "$t" && ! allowed_path "$t"; then echo x; return; fi
      else
        exempt "$t" "$kind" || { echo x; return; }
      fi
    done <<EOF
$list
EOF
  done
}

# True when any segment on stdin is risky for kind $1.
check() { [ -n "$(risky_segments "$1")" ]; }

# A single > redirect (not >>, 2>, or into /dev/null, $null, nul) overwrites its target.
redirect_risky() {
  rl=$(printf '%s' "$body" | grep -Eio '[[:space:]]>[[:space:]]*[^[:space:]>&"|;]+' |
    sed -E 's/^[[:space:]]*>[[:space:]]*//' | grep -Eiv '^(/dev/null|\$null|nul)$')
  [ -n "$rl" ] || return 1
  while IFS= read -r t; do
    exempt "$t" move || return 0
  done <<EOF
$rl
EOF
  return 1
}

delete_verbs='rm|rmdir|unlink|shred|del|erase|rd|ri|remove-item'
find_delete() { printf '%s\n' "$body" | grep -Eio -e "${start}find${sp}[^|;&\"]*-delete[^|;&\"]*" | sed -E 's/^[^[:alnum:]]*//'; }

reason=""
for group in "$@"; do
  case "$group" in
    delete)
      { segments "$delete_verbs"; find_delete; } | check delete &&
        reason="this permanently deletes files, bypassing the trash" ;;
    move)
      if { segments "mv|move|move-item|mi|truncate|tee|set-content|out-file|clear-content|clc"
        segments "cp|copy|copy-item|cpi|xcopy" |
          grep -Ei '[[:space:]](-[[:alpha:]]*f[[:alpha:]]*|--force)([[:space:]]|$)'; } | check move ||
        redirect_risky; then
        reason="this can overwrite or relocate existing files"
      fi ;;
    perms)
      if { segments "chown|chgrp|icacls|takeown|set-acl"
        segments chmod |
          grep -Ei '[[:space:]](-[[:alpha:]]*r[[:alpha:]]*|--recursive|0?777|0?666|([ao]|ugo)\+[rwx]*w)([[:space:]]|$)'; } | check perms; then
        reason="this changes file permissions or ownership"
      fi ;;
    disk)
      if hit "${start}dd${sp}[^|;&]*(if|of)=" ||
        hit "${start}(mkfs[.[:alnum:]]*|fdisk|sfdisk|parted|wipefs|diskpart|format-volume|clear-disk|remove-partition|initialize-disk)([[:space:]\"]|\$)" ||
        hit "${start}format${sp}[[:alpha:]]:"; then
        reason="this can wipe or reformat a disk"
      fi ;;
    outside)
      { segments "$delete_verbs|mv|move|move-item|mi|truncate|chmod|chown|chgrp|icacls|takeown"; find_delete; } | check outside &&
        reason="this reaches outside the project folder" ;;
  esac
  [ -n "$reason" ] && break
done

if [ -n "$reason" ]; then
  msg="Blocked by the project filesystem guardrails: $reason. Do not retry, rephrase or work around it: tell the user what you wanted to do and why, and let them run it or decide. Allowed without prompting: literal absolute paths strictly inside a temp folder (/tmp, /var/tmp, the TEMP or TMPDIR folder, which includes the session scratchpad) or inside a Claude session worktree (${wr:-<repo>/.claude/worktrees}/<name>/...), and, for deletes, relative build or dependency output such as node_modules, dist or bin. Paths with .., variables or wildcards in the folder part, relative paths into temp or worktrees, and anything after a cd get no exemption: use the literal absolute path. If the command only mentions the operation in text, for example in a commit message, reword it."
  printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"%s"}}\n' "$msg"
fi
exit 0
