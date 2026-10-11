# Issue tracking with `gh`

Run these from inside the repository, or add `-R OWNER/REPO` to target another one. An issue is addressed by number (`12`) or URL.

## Read

```sh
gh auth status                                  # confirm login
gh issue list                                   # open issues, newest first
gh issue list -s all -l bug -a @me -L 50        # state, label, assignee, limit
gh issue list -S "login error in:title"         # search
gh issue view 12                                # title, body, metadata
gh issue view 12 -c                             # include comments
gh issue list --json number,title,state -q '.[] | "\(.number) \(.title)"'
```

`--json <fields>` with `-q <jq>` gives output that is easy to parse; `gh issue view --help` lists the fields.

## Write

Ask the user first unless they requested the action explicitly.

```sh
gh issue create -t "Short title" -F body.md     # body from a file; -F - reads stdin
gh issue comment 12 -F comment.md
gh issue edit 12 -t "New title" --add-label bug --add-assignee @me
gh issue close 12 -r completed -c "Fixed in abc1234"   # -r also takes "not planned"
gh issue reopen 12
```

## Tips

- Pass multi-line text with `-F <file>` or `-F -` (stdin) instead of `-b "..."`; shell quoting mangles newlines and quotes, especially on Windows.
- Reference an issue in a commit or PR with `Closes #12` to close it on merge.
- Leave `-w`/`--web` and `-e` (editor) alone; they open interactive programs.
