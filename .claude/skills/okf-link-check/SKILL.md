---
name: okf-link-check
description: Find and fix missing links between concepts in the OKF knowledge catalog ({{CATALOG}}). Use after adding or editing concepts, when asked to "check links", "link the catalog", "find related documents", "find orphans", or whenever the catalog's graph needs tidying.
---

# OKF link check

The catalog's value is in its graph (see `AGENTS.md`). This skill finds
places where concepts should point to each other and adds those links with
prose that explains the relationship. OKF links are untyped, so the
relationship has to be stated in the surrounding sentence.

## 0. Work in your own worktree

Sessions never edit the main checkout. Start (or reuse) your own worktree,
at the latest `origin/main`, using the session id the SessionStart hook
gave you:

```
WT=$(python3 {{CATALOG}}/tools/okf.py session start --id <session id>)
```

It prints the worktree's path; below, `$WT` stands for that path. Shell
variables don't survive between tool calls, so write the path out in full
in each command. Do everything below inside it: read and edit files there,
and run `python3 "$WT/tools/okf.py"`. If `session start` fails, stop and tell the
user rather than editing the main checkout.

## 1. Run the report

```
python3 "$WT/tools/okf.py" links
```

The catalog CLI (`tools/okf.py`, see the Tooling section of `AGENTS.md`)
finds the catalog root on its own, runs from any directory, needs only the
standard library, and reports:

| Section | Meaning | Action |
|---|---|---|
| Broken links | Target file doesn't exist | Always fix: correct the path or remove the link |
| Relative links in concepts | Concept links not bundle-root absolute | Rewrite as `/dir/concept.md` (index files may stay relative) |
| Orphans | No other concept links to it (indexes don't count) | Find the concepts that should mention it |
| Dead ends | Links to no other concept | Find what it depends on, runs on, or is part of |
| Index drift | Concept or directory missing from its parent `index.md` | Add the listing |
| Unlinked mentions | Another concept's filename, `title` or `aliases` appears in body prose without a link | **Candidates only**: judge each one |

`--json` gives machine-readable output; `--check` prints only broken links
and exits non-zero when there are any.

## 2. Look for relationships the script can't see

Name matching only finds explicit mentions. Also read the `description` of
every concept (via `grep -h '^description:' -r --include='*.md' .` or the
`index.md` files) and look for pairs that are related without naming each
other: a service and the host it runs on, a playbook and the system it
diagnoses, a project and the infrastructure it deploys to, a symptom and
its root-cause concept. Orphans and dead ends are the best places to start.

## 3. Decide, then edit

For each candidate, read the surrounding text in the source concept and ask:

- Is this really a reference to the target concept, or a coincidental
  string (a hostname inside a command, a substring, a source path)?
- Would a reader of the source plausibly want to jump to the target?

If yes:

- Link the **first meaningful mention** in the body, not every one.
  Leave mentions in code blocks, tables of raw values and frontmatter alone.
- Use a bundle-root absolute path: `[build server](/infra/build-server.md)`.
- Make the sentence say *how* they relate ("runs on", "is diagnosed by",
  "stores its metrics in") if the existing prose doesn't already. Don't
  bolt on bare "See also" lists unless the relationship really is loose.
- When a relationship is important in both directions, link both ways.
- Don't change facts while linking. If you spot an error, fix it separately
  with honest provenance.
- If a concept is often called something other than its title or filename,
  add an `aliases:` list to its frontmatter (an extension key OKF allows) so
  future reports catch it.

Skip candidates that aren't real references; there's no need to record them.

## 4. Verify and record

1. Re-run the report. Broken links must be zero; the remaining unlinked
   mentions should all be ones you deliberately skipped.
2. Add one entry to the root `log.md` under today's date:
   `okf.py log "Linked related concepts across ... (okf-link-check)."`
   Linking alone doesn't change a concept's facts, so leave `generated` as
   it is.
3. Publish: `okf.py publish -m "<what was linked>" <each file you edited> log.md`.
   It commits only the files you name, lints them (and refuses on errors
   such as broken links), commits, runs
   `git pull --rebase origin main` (another session may have pushed while
   you worked) and pushes to `main`, per the catalog's auto-update rules.
   If the pull brought in new concepts, re-run the report afterwards; if
   publish reports a rebase conflict, it has aborted the rebase and left
   your commit local: stop and tell the user.
