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

## Where the catalog lives

The catalog's source of truth is catalog **`{{MCP_CATALOG}}` on the
{{MCP_SERVER}} MCP server** (an [okf-mcp](https://github.com/PeterGrace/okf_mcp)
server). Agents read and write it only through that server's MCP tools
(`mcp__{{MCP_SERVER}}__*` in Claude Code); see "Tooling" below. This git
repository is a **frozen snapshot** of the concepts as of the move to the
server, plus the repository machinery (`install/`, `tools/`, this file).
Don't read concepts from it or write them there; `tools/okf.py` refuses to.

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

- **Bundle:** a directory tree of markdown files. Catalog `{{MCP_CATALOG}}` on the {{MCP_SERVER}} server is the bundle.
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
  any project, to consult the catalog through {{MCP_SERVER}} and to add or
  update concepts when it learns something durable or changes a real
  system. It also copies the `okf-*` skills (`install/skills/`) to
  `~/.claude/skills/` so they work from every project. The catalog is also
  the sessions' primary memory: anything worth remembering goes here first,
  and into a private memory store only in addition. Four hooks in
  `~/.claude/hooks/` back this up:
  - `okf-session.py` (SessionStart) tells each session which catalog
    applies to it and its name on the {{MCP_SERVER}} server. A machine can
    have several catalogs, listed in `~/.claude/okf-catalogs.json`; a
    session uses the one whose `projects` cover its working directory, else
    the default one.
  - `okf-memory-mirror.py` (PostToolUse) reminds the agent whenever it
    saves a memory without touching the catalog.
  - `okf-reminder.py` (Stop and SessionEnd) reminds it to record what
    turns that touched real systems established (any {{MCP_SERVER}} call
    counts as touching the catalog). To save the cost of a reminder every
    turn, it batches: it reminds once 3 such turns have passed without
    touching the catalog, once the oldest is 20 minutes old, or when the
    context passes 150k tokens (`OKF_REMINDER_TURNS`,
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

  Those sessions **publish without review**, so expect agent-authored
  revisions; review them with `history` and `log.md`, and undo anything
  unwanted with `revert`. Agents doing this should keep each publish
  focused on one change and describe it clearly in its message.
- **Write through a changeset.** Several sessions work on the catalog at
  once. Each one calls `open_changeset`, passes the handle it returns as
  `changeset` to every edit, and calls `publish` when done; nothing is
  visible to others until then. Reads see the changeset's drafts only when
  given the handle. `list_changesets` finds a lost handle. Edits to
  `log.md` and `index.md` made with `log` and `index` are replayed onto
  newer text at publish, so concurrent entries don't conflict; any other
  document changed by someone else meanwhile makes `publish` refuse with a
  `Conflict`: re-read it and redo the edit in a fresh changeset, and if
  that fails too, stop and ask rather than force.
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
  `okf-review-oldest` skill (`install/skills/okf-review-oldest/`) every time
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
  The `okf-link-check` skill (`install/skills/okf-link-check/`) finds broken
  links, orphans, dead ends, index drift and unlinked mentions; run
  `links_report` after adding or editing concepts.
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
  alerts to chat"), and add a `log.md` entry with the details. The server's
  revisions (`history`) and `log.md` are the change log; concepts aren't.
- **Unfixed problems go in `/projects/things-to-fix.md`.** When a session
  finds a bug or weakness and it's decided not to fix it in that session
  ({{OWNER}} says to leave it, it's out of scope, or it needs {{OWNER}}'s
  decision), add an entry: what's wrong, why it matters, where it lives, a
  possible fix, the date, and a link to the concept with the detail.
  Something fixed in the same session doesn't go there; record the fix in
  the affected concept. Whoever fixes an entry removes it.
- **Reorganize sprawl.** The `okf-reorganize` skill
  (`install/skills/okf-reorganize/`) finds concepts that have grown into
  catch-alls (`sprawl`; `lint` warns above a threshold),
  classifies their sections and, with {{OWNER}}'s approval, splits them out
  with `split_concept` and `move_concept`. Unattended runs only queue the
  proposal as `open_questions`. Concepts of type `Backlog` (such as
  `/projects/things-to-fix.md`) are lists that grow by design, so they're
  exempt: `sprawl` leaves them out of its ranking and `lint` doesn't warn.

## Tooling

The {{MCP_SERVER}} server's MCP tools are the catalog's only interface. In
Claude Code they are `mcp__{{MCP_SERVER}}__<tool>`; the connection selects
catalog `{{MCP_CATALOG}}`, and every tool takes a `catalog` argument to name
it explicitly. Write tools need the changeset handle from `open_changeset`.

**Use the dedicated tools for frontmatter, `log.md`, `index.md` and
restructuring, and the edit tools for body prose.** Never reconstruct a
whole file to change one key. The server writes every timestamp from its
own clock (none can be passed in), changes only the key a tool writes,
refuses secrets and frontmatter that doesn't parse, and refuses to publish
files with lint errors. Without a `by` argument, stamps and revisions are
credited to the API key's actor, which can be a person's (a key made for
a person, or shared with one). So agents always pass
`by` (`claude-code/<model id>`) to `create_concept`, `stamp`, `review` and
`split_concept`, and `human:{{OWNER}}` only for a confirmation {{OWNER}}
really gave.

| Tool | What it does |
|---|---|
| `search`, `get_concept` (`links`, `raw`), `read_document` | Find and read concepts, `index.md`, `log.md`, `AGENTS.md` |
| `history`, `revert` | A document's revisions; stage an earlier revision (or a deletion) in a changeset |
| `open_changeset`, `pending_changes`, `list_changesets`, `discard`, `publish` | Changeset lifecycle |
| `create_concept` (`index_summary`) | New concept (the server writes `generated`), optionally listed in its folder's index |
| `edit_document`, `replace_body`, `set_frontmatter` | Exact text replacement, whole body, one descriptive key |
| `stamp` (`generated` / `verified`) | Set `generated` or append to `verified` with `{ by, at: now }` |
| `review`, `question`, `unquestion`, `open_questions` | `reviewed` and the `open_questions` queue |
| `add_source` | Append a `sources` entry |
| `log` (`kind`: Update, Creation, Change, Import) | The only way to write `log.md` |
| `index` | List a concept in its folder's `index.md` |
| `links_report`, `oldest`, `sprawl`, `lint` | Reports and checks; pass the handle to include your drafts |
| `move_concept`, `split_concept`, `delete_concept` | Restructuring (through the `okf-reorganize` skill, with {{OWNER}}'s approval); every link and listing is kept in step |

Machinery files (this file, `install/`, `tools/`, `.claude/`, root
`docs/` and `tests/`) are read-only on the server. They are maintained in
this git repository (with `OKF_GIT_MAINTENANCE=1` if you use `tools/okf.py`
here) and reach the server only by re-import with
`okf-mcp import {{MCP_CATALOG}} - --replace --only-machinery`; see
`docs/okf-mcp.md`.

`tools/okf.py`, the original command-line tool, stays in the repository
for that maintenance and for catalogs that aren't served. In this
repository it refuses every command except `session end|list|prune`
unless `OKF_GIT_MAINTENANCE=1` is set.
