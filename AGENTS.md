# AGENTS.md

## What this repository is

This repository is a personal knowledge catalog: a collection of documents in
Google's **Open Knowledge Format (OKF)**. Its purpose is to catalog and explain
anything that might be useful context in {{SCOPE}}: people, projects, systems,
infrastructure, services, devices, accounts, processes, decisions, and how they
relate to each other.

Treat the repository as an **OKF bundle**. When an agent needs background on
something in {{SCOPE}}, it should be able to find it here. When an agent learns
something durable that belongs here, it should be written here in OKF form.

## Learn the format

If you are not already familiar with OKF, read the spec before adding or
editing documents:

- Specification (authoritative): https://github.com/GoogleCloudPlatform/open-knowledge-format/blob/main/SPEC.md
- Repository (spec, sample bundles, reference tools): https://github.com/GoogleCloudPlatform/open-knowledge-format
- Google Cloud announcement: https://x.com/GoogleCloudTech/status/2067012903337664886
- Overview article: https://www.marktechpost.com/2026/06/16/google-cloud-introduces-open-knowledge-format-okf-a-vendor-neutral-markdown-spec-for-giving-ai-agents-curated-context/

The spec is versioned (`<major>.<minor>`). This catalog targets **OKF v0.2**. If
the spec has moved on, follow the current spec and update this file.

## OKF in brief

This is a summary only. When it disagrees with the spec, the spec wins.

- **Bundle:** a directory tree of markdown files. This git repository is the bundle.
- **Concept documents:** UTF-8 markdown files with a YAML frontmatter block and a
  free-form body. A concept's ID is its file path without `.md`
  (`/infra/build-server.md` is the concept `/infra/build-server`).
- **Reserved filenames:** `index.md` is a directory listing for progressive
  disclosure and carries no frontmatter. `log.md` is a dated, newest-first
  update history. Never use either name for a concept document.
- **Frontmatter:**
  - Required: `type` (free-form; types aren't centrally registered).
  - Recommended: `title`, `description`, `resource` (canonical URI of the
    underlying thing), `tags` (list).
  - Provenance: `sources` (list of entries with a required `resource`; optional
    `id`, `title`, `author`, `usage_count`, `last_modified`).
  - Trust: `generated: { by, at }` and `verified: [{ by, at }, ...]`.
  - Lifecycle: `status` (`draft`, `stable` (default), or `deprecated`) and
    `stale_after` (ISO 8601 UTC instant).
  - Extra keys are allowed; consumers preserve them.
- **Actors** in `by` fields: `<producer>/<version>` for agents (e.g.
  `claude-opus-5-5/1`), `human:<id>` for people, `process:<id>` for automation.
- **Links:** ordinary markdown links between concepts. Prefer bundle-root
  absolute paths (`/people/jane-doe.md`). Links are untyped relationships, so
  describe the relationship in the surrounding prose.
- **Conventional body headings:** `# Schema`, `# Examples`, `# Computation`.
- **`references/`** subdirectories hold external material, run instructions,
  and code that supports a concept.

## Example concept

```markdown
---
type: Service
title: Build server
description: CI server that builds and tests every pushed branch and publishes release images.
resource: https://ci.example.internal
tags: [ci, build, infrastructure]
status: stable
generated:
  by: claude-opus-5-5/1
  at: 2026-10-24T15:30:00Z
sources:
  - id: ci-runbook
    resource: https://wiki.example.internal/ci
    title: CI runbook
---

The build server runs on [the shared VM host](/infra/vm-host.md) and is exposed
to agents through an MCP integration. See [the network overview](/infra/network.md)
for how it is reached.
```

## Working in this repository

- **`AGENTS.md`, `CLAUDE.md`, `README.md`, `.claude/`, `tools/`,
  `install/`, the top-level `docs/` and `tests/`, `.okf-catalog.json`,
  `.gitignore`, `.gitattributes` and `.worktrees/` are repository
  machinery, not OKF concepts.** The markdown
  files intentionally have no frontmatter. Do not add a `type` to them, list
  them as concepts in an `index.md`, or flag them as nonconformant.
- **Claude Code sessions update this catalog automatically.** On each
  machine that uses it, `install/setup.py install` puts a block in the
  user-level `~/.claude/CLAUDE.md` that tells every Claude Code session, in
  any project, to consult its catalog and to add or update concepts when it
  learns something durable or changes a real system. The catalog is also
  their primary memory: anything worth remembering goes here first, and
  into a private memory store only in addition. Four hooks in
  `~/.claude/hooks/` back this up:
  - `okf-session.py` (SessionStart) tells each session which catalog
    applies to it, and its session id. A machine can have several catalogs,
    listed in `~/.claude/okf-catalogs.json`; a session uses the one whose
    `projects` cover its working directory, else the default one.
  - `okf-memory-mirror.py` (PostToolUse) reminds the agent whenever it
    saves a memory without touching the catalog.
  - `okf-reminder.py` (Stop and SessionEnd) reminds it to record what
    turns that touched real systems established. To save the cost of a
    reminder every turn, it batches: it reminds once 3 such turns have
    passed without touching the catalog, once the oldest is 20 minutes
    old, or when the context passes 150k tokens (`OKF_REMINDER_TURNS`,
    `OKF_REMINDER_MINUTES`, `OKF_REMINDER_CONTEXT`). A session that ends
    with turns still unrecorded gets a line in
    `~/.claude/okf-reminder/unrecorded.jsonl`.
  - `okf-greenfield.py` (PostToolUse on `Skill`, and UserPromptSubmit for
    typed slash commands) gives design and planning work a clean start.
    When a skill listed in `greenfield_skills` in
    `~/.claude/okf-catalogs.json` runs (by default the superpowers
    brainstorming, planning and plan-execution skills), it tells the
    session not to consult the catalog or memory stores unless asked, and
    to keep the owner's private details out of what it writes, since
    designs and plans often end up in public repositories.

  Those sessions **commit and push to
  `main` without review**, so expect agent-authored commits; review them in
  `git log` and revert anything unwanted. Agents doing this should keep each
  commit focused on one change and describe it clearly.
- **Write only in your own session worktree.** Several sessions work on the
  catalog at once, so none of them edits the main checkout. Run
  `tools/okf.py session start --id <session id>` (a SessionStart hook gives
  Claude Code sessions their id); it prints `.worktrees/<id>`, a worktree
  at the latest `origin/main`. Edit there, run *that worktree's*
  `tools/okf.py`, and publish from it. `session end --id <id>` removes it
  when you're done. Clean worktrees idle for a day are pruned
  automatically. To read, `git pull --rebase origin main` in the main
  checkout first, or read in your worktree. On a rebase conflict, stop and
  ask rather than force. `log.md` and `index.md` use git's `union` merge
  (`.gitattributes`), so lines that sessions add concurrently don't
  conflict.
- **One concept per file.** Use short, lowercase, hyphenated filenames. Group
  related concepts into directories by domain (for example `people/`,
  `projects/`, `infra/`, `services/`, `processes/`). Create directories as needed.
- **Keep `index.md` files current.** When you add, rename, or remove a concept,
  update the `index.md` in that directory (and the parent's, if you added a
  directory) so the bundle can be browsed top-down.
- **Record changes in `log.md`.** Add a dated, newest-first entry at the bundle
  root for meaningful additions or revisions.
- **Mark provenance honestly.** Set `generated` when an agent writes content.
  Add a `verified` entry only for checks that actually happened; a `human:`
  actor should be added only when a person really reviewed the content. List
  the `sources` the content came from.
- **`reviewed` is a catalog extension key**, written by the
  `okf-review-oldest` skill (`.claude/skills/okf-review-oldest/`) every time
  it re-checks a concept: `{ by, at, outcome, note }` with outcome
  `verified`, `updated`, `partial` or `unverifiable`. It records that a
  review happened even when nothing could be confirmed; `verified` is still
  added only when the facts really were confirmed.
- **`open_questions` is a catalog extension key**: a list of quoted questions
  about facts only {{OWNER}} can confirm, queued by unattended reviews. Anyone
  who gets an answer applies it to the concept and removes the question.
  Review outcomes never go in `status`, which OKF limits to `draft`,
  `stable` and `deprecated`.
- **Use `status: draft`** for content that is speculative or incomplete, and
  `stale_after` for facts that are known to expire.
- **Link generously.** The value of the catalog is in the graph. When a concept
  mentions another concept that exists here, link it.
  The `okf-link-check` skill (`.claude/skills/okf-link-check/`) finds broken
  links, orphans, dead ends, index drift and unlinked mentions; run
  `tools/okf.py links` after adding or editing concepts.
- **Never store secrets.** No passwords, API keys, tokens, or private keys.
  Describe where a credential lives (e.g. "in the password manager under X"),
  never its value.
- **Explain, don't just list.** Each concept should say what the thing is, why
  it matters, and how it relates to the rest of {{SCOPE}}.
- **Keep each concept about its subject.** Before adding a section to a
  concept, ask whether it's about this concept, or about something that
  runs on it or happened to it. An incident or investigation gets an
  incident concept (or goes in the affected system's concept), a check/fix
  procedure gets a `playbooks/` concept, another system gets its own
  concept, and the hub keeps one line and a link. A dated status snapshot
  goes in the system it describes, with `stale_after`.
- **Changes to real systems: one dated line plus a log entry, not a
  narrative.** Record a change you made in the affected concept as its new
  current truth, with at most one dated line ("Since 2026-10-24, the build server
  alerts to chat"), and add a `log.md` entry with the details. Git and
  `log.md` are the change log; concepts aren't.
- **Unfixed problems go in `/projects/things-to-fix.md`.** When a session
  finds a bug or weakness and it's decided not to fix it in that session
  ({{OWNER}} says to leave it, it's out of scope, or it needs {{OWNER}}'s
  decision), add an entry: what's wrong, why it matters, where it lives, a
  possible fix, the date, and a link to the concept with the detail.
  Something fixed in the same session doesn't go there; record the fix in
  the affected concept. Whoever fixes an entry removes it.
- **Reorganize sprawl.** The `okf-reorganize` skill
  (`.claude/skills/okf-reorganize/`) finds concepts that have grown into
  catch-alls (`tools/okf.py sprawl`; `lint` warns above a threshold),
  classifies their sections and, with {{OWNER}}'s approval, splits them out
  with `tools/okf.py split` and `mv`. Unattended runs only queue the
  proposal as `open_questions`. Concepts of type `Backlog` (such as
  `/projects/things-to-fix.md`) are lists that grow by design, so they're
  exempt: `sprawl` leaves them out of its ranking and `lint` doesn't warn.

## Tooling

`tools/okf.py` is the catalog's command-line tool (Python 3, standard library
only). Run it from any directory as
`python3 {{CATALOG}}/tools/okf.py <command>`; each command
has `--help`.

**Use it for frontmatter, `log.md`, `index.md` and publishing; use your normal
Edit/Write tools for body prose** (and to create a new concept's file). Don't
hand-edit the bookkeeping with heredocs, `sed` or string replacement: that is
how guessed, future-dated timestamps and broken frontmatter got in. The tool
writes every timestamp from the real current UTC time (none can be passed in)
and changes only the key it writes, leaving every other byte as it was. The
default actor is `claude-code/claude-opus-5-5` (override with `--by` or the
`OKF_ACTOR` environment variable).

| Command | What it does |
|---|---|
| `stamp <concept> generated` | Set `generated: { by, at: now }` |
| `stamp <concept> verified [--by human:{{OWNER}}]` | Append `{ by, at: now }` to `verified` |
| `review <concept> --outcome O --note TEXT [--question TEXT ...]` | Replace `reviewed`; queue `open_questions` |
| `unquestion <concept> <n-or-text>` | Remove an answered open question |
| `question <concept> TEXT` | Queue one open question without recording a review |
| `source <concept> --id ID --resource R [--title T] [--author A]` | Append a `sources` entry |
| `log TEXT [--kind Update\|Creation\|Change\|Import]` | Add a bullet under today's heading in the root `log.md` |
| `index <concept> SUMMARY [--section H]` | List the concept in its folder's `index.md` |
| `links [--json] [--check]` | Link report: broken links and `#anchors`, relative, orphans, dead ends, index drift, unlinked mentions |
| `oldest [-n N] [--json] [--open-questions]` | Concepts by last `generated`/`verified`/`reviewed` |
| `sprawl [CONCEPT] [-n N] [--json]` | Rank concepts by how much they need splitting (lines, sections, sources, volatile sections, dates), with candidate sections; `Backlog` concepts are exempt |
| `mv OLD NEW` | `git mv` a concept, rewrite every link to it (anchors kept), move its `index.md` listing; prints touched files |
| `split CONCEPT --section H --to NEW [--type T] [--title T] [--description D] [--stub TEXT] [--source ID ...]` | Carve a section into a new concept (frontmatter, footnotes, anchor links, index listing); the parent keeps a stub; prints touched files |
| `lint [--json]` | Check frontmatter, timestamps, links and anchors, indexes, sprawl and likely secrets; exits 1 on errors |
| `publish -m MESSAGE PATH...` | Lint, commit only the named files/directories, `git pull --rebase --autostash origin main`, push (`--all` commits everything) |
| `session start\|end --id ID` | Create (or reuse) and print, or remove, the session's worktree `.worktrees/ID` |
| `session list`, `session prune [--older-than H]` | Show session worktrees; remove clean, pushed ones idle for H hours |

`<concept>` can be `/infra/time-server.md`, `infra/time-server` or a file
path. `mv` and `split` restructure the bundle; use them through the
`okf-reorganize` skill, with {{OWNER}}'s approval. Name every file you changed
in `publish`, including `log.md` and any `index.md`; the other commands
print the files they write. Other
sessions may have uncommitted work in the same checkout, so `publish`
commits only the named paths and lists what it left alone. Use `--all`
only when you know nobody else is working there. It refuses on lint errors
in the files being published (errors elsewhere are shown as warnings) or
on unmerged paths, does nothing when there is nothing to publish, and on a
rebase conflict aborts the rebase, leaves the commit local and exits
non-zero: stop and tell {{OWNER}}.
