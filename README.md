# OKF catalog template

A starting point for a personal or team **knowledge catalog**: a git
repository of [Open Knowledge Format](https://github.com/GoogleCloudPlatform/open-knowledge-format)
(OKF v0.2) documents that Claude Code sessions read for context and keep up
to date as they work.

It includes:

- **`AGENTS.md` / `CLAUDE.md`:** the catalog's conventions: one concept
  per file, provenance, links, dated changes, a `things-to-fix` backlog, and
  how parallel sessions share the repository.
- **`tools/okf.py`:** a standard-library CLI for the bookkeeping. It stamps
  frontmatter with the real UTC time, maintains `log.md` and `index.md`, and
  can check links, lint, rank sprawl, split concepts, and publish.
  Each session writes in its own git worktree.
- **Skills** in `.claude/skills/`:
  - `okf-review-oldest` re-verifies the stalest concept;
  - `okf-reorganize` splits catch-all concepts;
  - `okf-link-check` fixes the link graph.
- **`install/`:** a one-time `init` that fills in your details, and an
  `install` that wires a machine's Claude Code to the catalog. The
  `install` adds four hooks and a block in `~/.claude/CLAUDE.md`.

## Start a new catalog

```sh
git clone <this template> ~/repos/acme-knowledge
cd ~/repos/acme-knowledge
git remote set-url origin <your new, empty repository>
python3 install/setup.py init --owner jdoe --scope "my work at Acme" --name "Acme knowledge catalog"
git add -A && git commit -m "Initialize catalog" && git push -u origin main
python3 install/setup.py install --default
```

`init` replaces the `{{OWNER}}`, `{{SCOPE}}` and `{{CATALOG}}` placeholders. It creates the starter
concepts: the root index, `log.md`, `/people/<owner>.md` and
`/projects/things-to-fix.md`. It also records the catalog's identity in
`.okf-catalog.json`. Clone to the path you'll keep it at, because `init`
writes that path into the instructions.

On another machine, clone the initialized catalog to the same path and run
`install` there.

## Several catalogs on one machine

`install` registers each catalog in `~/.claude/okf-catalogs.json`. Each
session uses one catalog:

1. the catalog it's working inside;
2. otherwise, the catalog whose `--projects` directories cover its
   working directory (the most specific match wins; shell wildcards are
   allowed);
3. otherwise, the one installed with `--default`.

The session is told about the others, and only reads them.

```sh
python3 ~/repos/acme-knowledge/install/setup.py install --projects ~/work '~/repos/acme-*'
python3 ~/repos/home-knowledge/install/setup.py install --default
python3 ~/repos/acme-knowledge/install/setup.py status ~/work/api   # which catalog applies here?
```

Pass `--memory-tool mcp__<server>__save_memory` to `install` if you use an
MCP memory server. The hooks then remind Claude to copy memories saved there
into the catalog too.

While a design or planning skill runs, the `okf-greenfield.py` hook tells
Claude to work without the catalog unless you ask, and to keep your private
details out of specs, plans and code. Choose the skills with
`"greenfield_skills": [...]` in `~/.claude/okf-catalogs.json`; an empty
list turns it off.

## Things to decide for your catalog

- **Pushing without review.** The instructions tell sessions to commit and
  push to `main` without asking, and you review in `git log`. For a shared
  team catalog, you may prefer branches and pull requests. If so, change the
  last bullet of `install/CLAUDE-block.md` and the "commit and push" bullet
  in `AGENTS.md`.
- **The commit trailer.** `tools/okf.py` adds a `Co-Authored-By` line naming
  the Claude model (`CO_AUTHOR`). It also has a default actor
  (`DEFAULT_ACTOR`, or the `OKF_ACTOR` environment variable).
- **Secrets.** The instructions forbid them, and `lint` flags likely ones,
  but a catalog for work may have stricter rules about what can be written
  down. Put those rules in `AGENTS.md`.

`install/` is skipped by `okf.py`, so it never shows up as concepts. Keep
it, so new machines can run `install`.
