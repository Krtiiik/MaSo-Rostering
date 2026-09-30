"""Read-only view of the GitHub issue backlog for the work-issue-backlog skill.

Usage (from the repo root, any Python 3.9+):
    python .claude/skills/work-issue-backlog/backlog.py ready [--skip N ...]
    python .claude/skills/work-issue-backlog/backlog.py spec-status <spec-number>

`ready` prints every open issue with its status and ends with a
`NEXT: <n>` line (or `NEXT: none`). A ticket is ready when it is open, not
a spec/parent, has no assignee, has no open blocker and is not skipped.

Blockers are the union of GitHub's native "blocked by" dependencies and the
issue references under the body's `## Blocked by` heading. A spec is an
issue titled `Spec:`/`Map:`, one with native sub-issues, or one that another
issue names under its `## Parent` heading.

`spec-status` lists every issue (open or closed) naming the spec as its
parent and ends with `ALL_CLOSED: yes|no`.

Only reads via `gh`; never writes.
"""

import json
import re
import subprocess
import sys

REF = re.compile(r"(?:/issues/|#)(\d+)")


def gh_json(*args):
    out = subprocess.run(["gh", *args], capture_output=True, text=True, encoding="utf-8")
    if out.returncode != 0:
        sys.exit(f"gh {' '.join(args)} failed: {out.stderr.strip()}")
    return json.loads(out.stdout or "null")


def repo():
    return gh_json("repo", "view", "--json", "nameWithOwner")["nameWithOwner"]


def all_issues(repo_name, state):
    pages = gh_json("api", "--paginate", "--slurp",
                    f"repos/{repo_name}/issues?state={state}&per_page=100")
    return [i for page in pages for i in page if "pull_request" not in i]


def section(body, heading):
    """Text under `## <heading>` up to the next `## ` heading."""
    m = re.search(rf"^##\s*{heading}\s*$(.*?)(?=^##\s|\Z)", body or "", re.M | re.S | re.I)
    return m.group(1) if m else ""


def refs(text):
    return [int(n) for n in REF.findall(text)]


def parent_of(issue):
    found = refs(section(issue.get("body"), "Parent"))
    return found[0] if found else None


def cmd_ready(skip):
    name = repo()
    everything = all_issues(name, "all")
    state = {i["number"]: i["state"] for i in everything}
    open_issues = sorted((i for i in everything if i["state"] == "open"), key=lambda i: i["number"])
    parents = {parent_of(i) for i in everything} - {None}

    nxt = None
    for i in open_issues:
        n, title = i["number"], i["title"]
        is_spec = (re.match(r"\s*(spec|map)\s*:", title, re.I)
                   or (i.get("sub_issues_summary") or {}).get("total", 0) > 0
                   or n in parents)
        blockers = set(refs(section(i.get("body"), "Blocked by")))
        if (i.get("issue_dependencies_summary") or {}).get("total_blocked_by", 0):
            deps = gh_json("api", f"repos/{name}/issues/{n}/dependencies/blocked_by")
            blockers |= {d["number"] for d in deps}
            state.update({d["number"]: d["state"] for d in deps})
        open_blockers = sorted(b for b in blockers if state.get(b, "open") == "open")
        assignees = [a["login"] for a in i.get("assignees") or []]

        if is_spec:
            status = "spec"
        elif n in skip:
            status = "skipped this run"
        elif assignees:
            status = "assigned to " + ",".join(assignees)
        elif open_blockers:
            status = "blocked by " + ", ".join(f"#{b}" for b in open_blockers)
        else:
            status = "READY"
            nxt = nxt or n
        print(f"#{n}\t{status}\t{title}")
    print(f"NEXT: {nxt or 'none'}")


def cmd_spec_status(spec):
    children = [i for i in all_issues(repo(), "all") if parent_of(i) == spec]
    for i in sorted(children, key=lambda i: i["number"]):
        print(f"#{i['number']}\t{i['state']}\t{i['title']}")
    done = bool(children) and all(i["state"] == "closed" for i in children)
    print(f"ALL_CLOSED: {'yes' if done else 'no'}")


def main(argv):
    sys.stdout.reconfigure(encoding="utf-8")
    if argv[:1] == ["ready"]:
        skip = {int(a) for a in argv[1:] if a.isdigit()}
        cmd_ready(skip)
    elif argv[:1] == ["spec-status"] and len(argv) == 2:
        cmd_spec_status(int(argv[1]))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
