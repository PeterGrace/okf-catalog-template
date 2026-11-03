# Greenfield notice for design and planning skills: design

- **Date:** 2026-10-27
- **Status:** implemented

## Problem

The catalog's CLAUDE.md block tells every session to check the catalog before
working on anything in its scope, and catalog facts are also mirrored into
memory stores. A session that brainstorms or plans a piece of software meant
for publication can therefore carry the owner's private details (internal
hostnames, domains, registries, cluster and repository names, names and email
addresses) into the specs, plans, code and test fixtures it writes. Once
pushed to a public repository, those details are disclosed, and removing them
from history is costly.

Knowing that a repository is public isn't enough: a session can apply that
knowledge to data files and still write private values into its own prose.
The guidance has to arrive at the moment the design or plan is being written.

## Goal

When a listed skill (by default the superpowers design, planning and
execution skills) starts, the session gets a "greenfield" notice: don't
consult the catalog or memory stores for this work unless the user asks, and
keep what is already known about the owner's systems out of everything
written. The user adds catalog context deliberately, in a later turn, when
they want it.

## Decisions

| Question | Decision |
|---|---|
| Trigger | The skill being invoked, not the repository. The notice fires in every repository, public or private |
| Hook events | PostToolUse with matcher `Skill`, plus UserPromptSubmit for typed slash commands (dropped if those turn out to go through the Skill tool) |
| Which skills | `greenfield_skills` in `~/.claude/okf-catalogs.json`; a default list when the key is absent |
| Strength | Advisory context only. Nothing is blocked. A mechanical guard is out of scope |
| Already-loaded context | Not removed (a hook can't). The notice governs what is written, so timing mid-session is fine |

## Components

### `install/hooks/okf-greenfield.py`

A hook script in the same style as the other okf hooks: reads the hook JSON
from stdin, prints a `hookSpecificOutput` with `additionalContext` when it
applies, prints nothing otherwise, and always exits 0 (any exception is
swallowed so a session is never broken).

- **PostToolUse:** applies when `tool_name` is `Skill` and
  `tool_input.skill` is in the list.
- **UserPromptSubmit:** applies when the prompt, after leading whitespace,
  starts with `/<name>` for a listed name, followed by whitespace or the end
  of the prompt.
- Names match exactly (`superpowers:brainstorming` doesn't match
  `superpowers:brainstorming-extra`).

The notice text, with `<skill>` filled in:

> Greenfield: `<skill>` is running. For this work, don't read the knowledge
> catalog or any memory store (memory MCP tools, `~/.claude/projects/*/memory`)
> unless the user asks in this conversation. Keep anything you already know
> about the owner's systems out of every file and commit message you write
> (specs, plans, code, tests, fixtures): no real hostnames, domains,
> registries, cluster or repository names, IP addresses, or personal names
> and email addresses. Use placeholders such as `example.com` and
> `example.internal`. When you dispatch subagents, include this rule in their
> prompts.

### `install/hooks/okf_catalogs.py`

Adds `DEFAULT_GREENFIELD_SKILLS` and a `greenfield_skills(config)` helper
that returns the configured list, or the default when the key is absent. An
empty list disables the notice.

Default list:

- `superpowers:brainstorming`
- `superpowers:writing-plans`
- `superpowers:executing-plans`
- `superpowers:subagent-driven-development`
- `superpowers:brainstorm`, `superpowers:write-plan`,
  `superpowers:execute-plan` (deprecated aliases)

The module docstring's config example gains the key.

The notice doesn't depend on a catalog being selected for the session; it
fires even when `okf-catalogs.json` lists no catalog that applies, since
memory stores can leak on their own.

### `install/setup.py`

The `HOOKS` table holds one script per event, and PostToolUse is already
taken by `okf-memory-mirror.py`. It becomes a list of
`(event, matcher, script)` entries so one event can carry several scripts;
`merge_settings` and `install_hooks` iterate it. The memory-mirror matcher
keeps its special case (Write, Edit plus `memory_tools`). New entries:

- `("PostToolUse", "Skill", "okf-greenfield.py")`
- `("UserPromptSubmit", None, "okf-greenfield.py")`

Existing settings are merged as today: an entry is recognised by its command
and left alone apart from its matcher.

### `install/CLAUDE-block.md`

The "Before working on something within the catalog's scope, check it for an
existing concept" bullet gains: "unless a greenfield notice is active for the
current work; then use the catalog only when I ask."

### `AGENTS.md`

The hook list under "Claude Code sessions update this catalog automatically"
describes `okf-greenfield.py` and the `greenfield_skills` key.

## To confirm during implementation

1. Whether a typed `/plugin:skill` command reaches the Skill tool (and so
   PostToolUse). If it does, drop the UserPromptSubmit registration.
2. That PostToolUse `additionalContext` on a Skill call reaches the model.
   If it doesn't, fall back to PreToolUse with `additionalContext`.

Checked 2026-10-28 with `claude -p --settings` runs that loaded only this
hook: a Skill tool call delivered the notice (a run without the hook didn't
see one), and a typed `/superpowers:brainstorming` didn't go through the
Skill tool, so it got the notice only through UserPromptSubmit, which stays.

## Error handling

- Missing or malformed `okf-catalogs.json`: use the default list.
- Malformed stdin, missing fields, non-string values: print nothing, exit 0.
- `greenfield_skills` that isn't a list of strings: ignore the bad entries.

## Testing

- Script tests feeding sample hook JSON on stdin, with `HOME` pointed at a
  temporary directory: a listed skill via PostToolUse; an unlisted skill;
  a prefix-only near match; a slash-command prompt; a slash command with
  arguments; an ordinary prompt; a missing config (defaults apply); an empty
  list (nothing fires); malformed input (no output, exit 0).
- `setup.py install` against a temporary `HOME` with an existing
  `settings.json`: both new entries are added, the memory-mirror entry is
  untouched, and a second run changes nothing.
- One live check in a scratch session: invoke a listed skill and confirm the
  notice appears in context.

## Out of scope

- A mechanical guard (a PreToolUse hook on Write/Edit, or a git pre-push
  scan) that refuses private patterns in public repositories.
- Removing private details already published in any repository.
