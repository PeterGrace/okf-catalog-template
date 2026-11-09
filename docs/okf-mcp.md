# Moving a catalog to an okf-mcp server

A catalog made from this template starts as a git repository: sessions
write in their own worktrees and publish with `tools/okf.py`. An
[okf-mcp](https://github.com/PeterGrace/okf_mcp) server can serve the
catalog instead. The server keeps the catalog in a database, gives every
agent harness read and write access through MCP tools, and enforces the
catalog's rules (timestamps, lint, links, secrets) itself. Once a catalog
moves, the server is its source of truth, and the git repository becomes
a frozen snapshot that holds the repository machinery (`AGENTS.md`,
`install/`, `tools/`).

This guide moves an existing catalog. It is written so that a Claude Code
session on the catalog's machine can follow it step by step. Steps marked
**operator** run on the okf-mcp server (its `okf-mcp` command-line tool
talks to the server's database directly); a session that has no shell
there hands those commands to the owner. Commands that create or show a
secret, such as an API key, are always for the owner to run, so the key
never enters a session's context.

Placeholders below: `NAME` is the catalog's name on the server (a short
id, such as `acme`), `SERVER` is the server's name in Claude Code's MCP
config (`okf-mcp` unless you chose another; its tools are
`mcp__SERVER__*`), and `<catalog>` is the catalog's checkout.

## 1. Server: create the catalog and a key (operator)

```sh
okf-mcp catalog create NAME --description "What the catalog covers"
okf-mcp key create claude --access write --catalogs NAME --default NAME --actor claude-code
```

`key create` prints the key once. The owner stores it in a password
manager and in an environment variable, such as `OKF_MCP_KEY`, on each
machine that will use the catalog. If the server runs in Kubernetes, run
each command inside its pod, for example
`kubectl -n okf-mcp exec deploy/okf-mcp -- okf-mcp ...` (add `-i` when
the command reads stdin). okf-mcp's `docs/operations.md` covers the rest.

## 2. Each machine: connect Claude Code to the server

```sh
claude mcp add --scope user --transport http SERVER https://okf-mcp.example.com/mcp \
    --header "Authorization: Bearer ${OKF_MCP_KEY}"
```

Restart Claude Code. Check that `list_catalogs` (the tool
`mcp__SERVER__list_catalogs`) lists `NAME`. An empty catalog is fine at
this point.

## 3. The catalog: bring in this template's machinery

Skip this step for a catalog made from a version of this template that
already has `install/setup.py serve`.

Make sure no session has unpublished work: `python3 <catalog>/tools/okf.py
session list` should show only clean worktrees, and `git -C <catalog>
status` should be clean on `main`, up to date with `origin/main`. Then
take the template's `install/` and `tools/okf.py`, which are not filled in
per catalog (`serve` fills in `okf.py` in the next step):

```sh
cd <catalog>
git fetch https://github.com/PeterGrace/okf-catalog-template main
git checkout FETCH_HEAD -- install/ tools/okf.py
```

Check `git status`: only `install/` and `tools/okf.py` should have
changed. Leave `AGENTS.md` and `.claude/skills/` alone; `serve` replaces
them.

## 4. The catalog: switch it to the server

```sh
python3 install/setup.py serve --catalog NAME --server SERVER
```

`serve` records the server and `NAME` in `.okf-catalog.json`, replaces
`AGENTS.md` with its okf-mcp version (`install/AGENTS-mcp.md`, filled in
with the catalog's owner and scope), and removes the git-workflow skills
from `.claude/skills/`. Review `git diff AGENTS.md`, and copy back any
rules you had added to the old one. Then commit and push with git itself
(`tools/okf.py` now refuses to run here):

```sh
git add -A && git commit -m "Serve the catalog from okf-mcp catalog NAME" && git push origin main
```

From this commit on, the checkout is frozen. Other machines get the
freeze when they pull it.

## 5. Server: import the catalog (operator)

Import exactly the commit from step 4: `git archive` contains only the
tracked files, so worktrees and untracked files stay out.

```sh
git -C <catalog> archive --format=tar.gz HEAD | okf-mcp import NAME -
```

With Kubernetes, pipe it into the pod:
`... | kubectl -n okf-mcp exec -i deploy/okf-mcp -- okf-mcp import NAME -`.
Re-importing into a catalog that already has content needs `--replace`.

To check the import, export the catalog and compare it with the commit.
The two trees should match:

```sh
mkdir git-tree server-tree
git -C <catalog> archive HEAD | tar -x -C git-tree
okf-mcp export NAME - | tar -xz -C server-tree
diff -r git-tree server-tree
```

## 6. Each machine: reinstall

On every machine that uses the catalog, pull the checkout, then run
`install` again. Its `--projects` and `--default` settings are kept unless
you pass new ones:

```sh
git -C <catalog> pull --rebase origin main
python3 <catalog>/install/setup.py install
python3 <catalog>/install/setup.py status
```

`install` copies the MCP-aware hooks and adds `"mcp"` to the catalog's
entry in `~/.claude/okf-catalogs.json`. It copies the okf-mcp versions of
the `okf-*` skills to `~/.claude/skills/`, naming `SERVER` in them, and
leaves alone a skill that is already a symlink there. It also rewrites the
`~/.claude/CLAUDE.md` block, which then covers the okf-mcp workflow (and
the git workflow too, if another catalog on the machine still uses git).
`status` shows the catalog as `okf-mcp catalog NAME on SERVER`.

Start a new Claude Code session and check:

- the SessionStart context names `catalog NAME on the SERVER MCP server`;
- `read_document` with path `AGENTS.md` returns the okf-mcp version;
- `python3 <catalog>/tools/okf.py lint` refuses, naming the server.

## Afterwards: changing the machinery

The server refuses writes to machinery (`AGENTS.md`, `install/`, `tools/`,
`.claude/`, the root `docs/` and `tests/`). Change these files in the git
checkout and commit them as usual. Set `OKF_GIT_MAINTENANCE=1` if you need
`tools/okf.py` there. Then copy only the machinery to the server, which
leaves the concepts published since the move as they are (operator):

```sh
git -C <catalog> archive --format=tar.gz HEAD | okf-mcp import NAME - --replace --only-machinery
```

A plain `--replace` from git would instead roll every concept back to the
frozen snapshot.

## Going back to git

Revert the step 4 commit, which restores the git-workflow `AGENTS.md`,
skills and `.okf-catalog.json`. Then lay the server's concepts over the
checkout, leaving out the machinery that the revert just restored
(operator, for the export):

```sh
git -C <catalog> revert --no-edit <step 4 commit>
okf-mcp export NAME - | tar -xz -C <catalog> --anchored --exclude=AGENTS.md \
    --exclude=.okf-catalog.json --exclude=install --exclude=tools \
    --exclude=.claude --exclude=docs --exclude=tests
```

(`--anchored`, in GNU tar, matches each name from the archive root, so
a concept folder such as `infra/docs/` is still extracted.)

Check `git status`, delete any concept the server no longer has, then
commit, push, and run `install` again on each machine.
