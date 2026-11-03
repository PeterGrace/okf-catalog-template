---
name: okf-reorganize
description: Reorganize a sprawling concept in the OKF knowledge catalog ({{CATALOG}}) for progressive disclosure, so hub concepts stay short and link out to incident, playbook and child-system concepts. Use when asked to "reorganize the catalog", "split a concept", "this concept is too long", "tidy up build-server.md", when `okf.py lint` shows a `sprawl` warning, or for routine catalog structure maintenance. Accepts an optional concept path to work on that one instead of the worst.
---

# Reorganize a sprawling concept

Hub concepts (a cluster, a network, a service) collect things that aren't
about the hub: an incident investigated on it, the fix procedure that came
out of it, a change log of what an agent did, a status snapshot from one
afternoon, another system that runs on it. Each addition is reasonable;
together they bury the thirty lines that say what the thing *is*. This skill
moves each of those to where it belongs, so a reader gets the hub in a
screen and follows links for the rest.

## Mode

- **Interactive** (default): the user invoked this skill or asked for a
  reorganization in a conversation. Propose, ask, then execute only what
  {{OWNER}} approves.
- **Autonomous**: running unattended (`/loop`, `/schedule`, cron, headless
  `claude -p`, a workflow, or the user said not to ask). **Never
  restructure.** Moving and splitting change what other sessions read and
  where they write, so they need {{OWNER}}'s approval. Only record the
  proposal (step 5).

If unsure, treat it as interactive.

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
and run `python3 "$WT/tools/okf.py"` (below, `okf.py`). If `session start`
fails, stop and tell the user rather than editing the main checkout.

## 1. Pick the concept

```
okf.py sprawl            # top 5; -n N for more, --json for machine output
okf.py sprawl <concept>  # one concept
```

Each row shows the score and its parts: non-blank body lines, headings,
sources, volatile headings or `**Lead-in.**` paragraphs (as of, current
state, outage, change log, open items, trap, fix, stuck, ...) and distinct
dates. Under it are the split candidates: volatile sections, sections
holding a fifth of the body, and volatile lead-in paragraphs, with line
numbers. `lint` warns above the threshold printed in the header.
Concepts of type `Backlog` (e.g. `/projects/things-to-fix.md`) grow by
design and are exempt: the ranking skips them, and naming one shows its
score marked exempt. Don't reorganize them with this skill.

Take the top concept unless the user named one. The score only points;
read the whole concept before deciding anything.

## 2. Classify every section

Read the concept, the concepts it links to and the ones linking to it
(`grep -rn '<concept path>' --include='*.md' "$WT"`). For each section,
and each long lead-in paragraph inside a section, decide what it really is:

| Section is really… | Where it goes |
|---|---|
| Another system that runs on this one | its own concept; hub keeps one line + link |
| An incident/investigation | incident concept or the affected system's concept |
| A fix procedure (check/fix steps) | a playbooks/ concept |
| A change-log entry | log.md + git; concept keeps only current truth (one dated line at most) |
| A dated status snapshot | delete if stale, or move to the system's concept with stale_after |

Anything else that describes what the thing is, how it's built, how it's
reached or how it behaves stays in the hub. So do short facts (one or two
lines) even when they're dated.

Before proposing a new concept, check whether a home already exists: an
existing concept for the affected system, an existing playbook, an
existing `incidents/` or `playbooks/` folder near the hub (for example
`infra/playbooks/`). Prefer extending one over
creating a near-duplicate. Match the neighbours' naming and `type`s
(`Playbook`, `Incident`, `System`, ...).

A section often mixes kinds. A typical incident section holds the
incident narrative, a check/fix procedure and a change log; plan each part
separately (the incident goes to an incident concept, the procedure to a
playbook that the incident links to, the change log goes away).

## 3. Write the plan

For each move, give: the section (heading and line range), its kind, the
destination (new path, or existing concept), the new concept's `type`,
title and one-sentence description, which of the parent's sources it
needs, and the one line the hub keeps. Also list:

- deletions (stale snapshots, change logs whose facts are already in
  `log.md` and git; check `git log -S'<phrase>'` and `log.md` first, and
  keep a single dated line in the hub if the change is still relevant);
- inbound links that will be rewritten (the tools do this; listing them
  lets {{OWNER}} see the blast radius);
- anything you'd leave alone, and why.

## 4. Interactive: ask, then execute what's approved

Present the plan with AskUserQuestion: one question per move (up to four
per call; more calls if needed), each quoting the section and the proposed
destination, with options "Do it", "Different destination" (they explain),
"Leave it" and "Delete instead" where deletion makes sense. Execute only
the approved moves.

Tools:

```
okf.py split <concept> --section "<heading>" --to <new path> --type <Type> \
    --title "<title>" --description "<one sentence>" [--source <id> ...] [--stub "<hub line>"]
okf.py mv <old path> <new path>
```

`split` moves the section's content (subsections included) into a new
concept, drops its heading (it becomes the title) and re-levels its
subsections to start at `#`. The new concept gets `generated` now, the
parent's `status`, and sources: the `--source` ids if given, else those the
section's footnotes cite, else all of the parent's (prune them by hand;
`split` says which rule it used). It never copies `verified`: splitting
isn't verification. The parent keeps the heading with a stub paragraph
(`--stub`, or the link plus `--description`). Footnotes go where they're
cited, links to `PARENT#section` and its subsections are rewritten across
the bundle, and the new concept is listed in its folder's `index.md`
(created, and listed in the parent index, for a new folder).

`mv` renames or moves a concept with `git mv`, rewrites every link to it
(anchors kept), and moves its `index.md` listing.

Both print the files they touched; keep the list for publishing. Then
finish by hand:

1. **Prose.** Rewrite the new concept's opening line ("Split out of …") into
   a real explanation of what it is and how it relates to the hub. Trim a
   section that ran to the end of the document (`split` warns) of closing
   paragraphs that belong to the hub, and move them back. Merge a stub
   into the surrounding hub prose if a heading for one line reads badly.
   Replace any `TODO` lines in newly created `index.md` files.
2. **Splitting a section further.** To split part of a section (say, the fix
   procedure inside an incident), first give it its own heading in the new
   concept, then `split` again from there.
3. **Deletions.** Remove change-log paragraphs whose facts are in `log.md`
   and git; leave one dated line in the hub if the change still matters
   (e.g. "Since 2026-10-24, the build server alerts to chat").
4. **Frontmatter.** Prune copied sources the new concept doesn't use, and
   remove from the hub sources no longer used there
   (both by editing the YAML carefully, as there's no command for removal);
   add `stale_after` to a moved status snapshot; set `type`. Stamp
   `generated` on the hub (`okf.py stamp <hub> generated`), since its content
   changed. Don't add `verified`.
5. **Check.** `okf.py links` (no broken links or anchors; link the new
   concepts generously), `okf.py lint`, and `okf.py sprawl <hub>` to see the
   score drop.
6. **Record.** `okf.py log 'Reorganized `/infra/x.md`: moved … to …, … (okf-reorganize).' --kind Change`
7. **Publish**, naming every touched file, including deleted/moved paths,
   `log.md` and each `index.md`:
   `okf.py publish -m "Reorganize <hub>: <what moved where>" <files...>`.
   On a rebase conflict, it aborts and leaves the commit local: stop and
   tell the user.

## 5. Autonomous: record the proposal only

Don't run `split` or `mv`, and don't edit prose. Queue the plan on the
concept as one self-contained open question per move, without stamping
`reviewed` (nothing was re-checked):

```
okf.py question <concept> "Reorganize proposal (okf-reorganize, <YYYY-MM-DD>): split '# Stuck deploys on the build server' (L112-176, an incident with a fix procedure and a change log) into /infra/incidents/build-server-stuck-deploys.md and /infra/playbooks/build-server-stuck-deploy.md; drop the change log (in log.md). Approve?"
```

Take the date from `date -u +%Y-%m-%d`. Skip a proposal already queued.
Then `okf.py log '... (okf-reorganize, proposal only)'` and publish the
concept and `log.md`. An interactive session answers the questions later
(`okf.py oldest --open-questions`), runs this skill on the concept, and
removes each answered question with `okf.py unquestion`.

## 6. Report

Which concept, its sprawl score before and after, each move made (or
proposed) with its destination, the deletions, files touched, the commit,
and anything left for {{OWNER}} (TODOs in new indexes, unpruned sources,
questions queued).
