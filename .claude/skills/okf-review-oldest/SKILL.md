---
name: okf-review-oldest
description: Re-check the least recently touched concept in the OKF knowledge catalog ({{CATALOG}}) against the real world, correct it if needed, and stamp it with the review date. Use when asked to "review the oldest concept", "verify the catalog", "check if the catalog is still accurate", "answer the catalog's open questions", or to do routine catalog freshness maintenance. Accepts an optional concept path to review that one instead.
---

# Review the oldest concept

Picks the concept whose knowledge was touched longest ago, investigates
whether it's still true, and records the result in its frontmatter. Each
run stamps the concept, so repeated runs rotate through the whole catalog.

The catalog covers everything in {{SCOPE}}, not just systems you can
log in to. Many facts came from {{OWNER}} (decisions, preferences, history,
things about people, teams, accounts) and only {{OWNER}} can confirm them.
How those are handled depends on the mode.

## Mode

- **Interactive** (default): the user invoked this skill or asked for a
  review in a conversation. You may ask the user questions.
- **Autonomous**: running unattended, from `/loop`, `/schedule`, a cron or
  headless `claude -p` run, a workflow, or the user said not to ask. Never
  ask questions or wait for answers; queue them in `open_questions` instead.

If unsure, treat it as interactive.

## Frontmatter this skill writes

OKF v0.2 (SPEC §5.2) already defines two of these; `reviewed` is a catalog
extension key, which OKF allows.

| Key | Meaning | When to write it |
|---|---|---|
| `reviewed` | The latest review by this skill: `by`, `at`, `outcome`, `note` | **Every run**, whatever the outcome. Replace the previous value; history lives in git and `log.md`. |
| `verified` | OKF: the content was confirmed against its sources | Only when the investigation actually confirmed the concept's key facts (outcomes `verified` and `updated`). Append `{ by, at }` to the list. |
| `generated` | OKF: when the content last meaningfully changed, and by whom | Only when you changed facts (outcome `updated`). |
| `open_questions` | Catalog extension: questions only the user can answer, as a list of quoted strings | Autonomous runs add them; whoever answers one removes it. Delete the key when the list is empty. |

Don't put review outcomes in `status`: OKF only allows `draft`, `stable` and
`deprecated` there. `reviewed.outcome`, the `open_questions` list and the
absence of a fresh `verified` entry are what mark a concept as unconfirmed.

Outcomes:

- **`verified`**: every key fact you could check matched.
- **`updated`**: you found something wrong or out of date and corrected it.
  The corrected content was checked, so it also gets a `verified` entry.
- **`partial`**: some key facts were confirmed, others couldn't be checked.
  No `verified` entry, since `verified` vouches for the whole concept. The
  note lists what was and wasn't checked.
- **`unverifiable`**: the key facts couldn't be checked at all. No
  `verified` entry; the note says why and what access would allow it.

Format (use a block mapping, and quote the note):

```yaml
reviewed:
  by: claude-code/claude-opus-5-5
  at: 2026-10-24T18:05:00Z
  outcome: partial
  note: "Confirmed FRR version and BGP sessions live; couldn't reach the Neptune looking glass to check the announcement."
```

Write all of these with the catalog CLI, `tools/okf.py` (see the Tooling
section of `AGENTS.md`), never by hand: it stamps every `at` with the real
current UTC time and edits only the key it writes. Below, `okf.py` means
`python3 "$WT/tools/okf.py"`, run in your worktree (step 1). Its default actor is
`claude-code/claude-opus-5-5`; pass `--by claude-code/<model-id>` if you are
a different model, and `--by human:{{OWNER}}` for confirmations {{OWNER}} gave.

| Write | Command |
|---|---|
| `reviewed` (+ queued questions) | `okf.py review <concept> --outcome partial --note "..." [--question "..." ...]` |
| `verified` entry | `okf.py stamp <concept> verified [--by human:{{OWNER}}]` |
| `generated` | `okf.py stamp <concept> generated` |
| `sources` entry | `okf.py source <concept> --id live-20261024 --resource "..." [--title ...] [--author ...]` |
| Remove an answered question | `okf.py unquestion <concept> <number-or-exact-text>` |

## 1. Get a worktree and pick

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

```
python3 "$WT/tools/okf.py" oldest
```

The command lists the five least recently touched concepts: the latest of
`generated.at`, `verified[].at` and `reviewed.at`; ties broken by path;
deprecated concepts skipped; `STALE` marks a passed `stale_after`; `?N`
counts queued `open_questions`. Take the first one unless the user named a
concept.

In interactive mode, also run `okf.py oldest --open-questions`
(it numbers each concept's questions, for `okf.py unquestion`). If any concept
has queued questions, offer to go through those before (or instead of)
the oldest concept. They're the cheapest way to raise the catalog's trust.

## 2. Investigate (read-only)

1. Read the whole concept, its `sources`, and the concepts it links to.
   The catalog itself often says how to reach a system (an Access row, a
   kubectl context, an API).
2. Pick out the **key facts**: identity, how it's reached, addresses,
   versions, configuration, ownership, current status, and any "not yet
   applied" or "as of" claim. Historical narrative ("on 2026-09-28 X
   happened") can't go stale; don't try to re-prove it.
3. Check each key fact against the live source with **read-only** commands:
   `ssh <host>` with show/cat/ip/systemctl status, `kubectl get/describe`,
   `vtysh -c 'show ...'`, public APIs with curl, `gh api` GETs, reading the
   source repo, MCP read tools.
4. **Never change a real system during a review**, even to fix something
   obvious. If the system is wrong rather than the doc, record what you
   found in the concept and tell the user; fixing is a separate, explicit
   task.

Keep it proportionate: a few minutes per concept, not a new investigation.

## 3. When it can't be validated

Sort each fact you couldn't confirm into one of these:

- **Only the user knows** (the source is `human:` or a conversation, or
  it's a decision, preference, plan, history, or anything about people,
  places or accounts with no system to check).
- **Couldn't reach it** (host unreachable, no credentials, MCP server down).
  Try the obvious alternative routes first, e.g. another host, a public API,
  or a read-only path the catalog documents.
- **Looked and it's gone or different** (host decommissioned, URL 404s,
  config changed). That's a finding, not a gap: outcome `updated`. Correct
  the concept. If the thing no longer exists, set `status: deprecated` and
  say in the body what replaced it, if anything.

Then, depending on the mode:

**Interactive.** Stop and ask the user before writing anything. Use
AskUserQuestion, up to four questions per call. Quote each claim and offer
"Still true", "Changed" (they explain), "No longer applies" and "Don't
know". Also ask about unreachable facts if the user might know, or might
grant access. Apply the answers:

- Confirmed: it counts as checked. Add a `verified` entry for
  `human:{{OWNER}}` (a person really confirmed it), plus one for yourself if
  you machine-checked the rest. Add a `sources` entry such as
  `{ id: review-20261024, resource: "Conversation with {{OWNER}}, 2026-10-24", author: human:{{OWNER}} }`.
- Changed or no longer applies: correct the concept, outcome `updated`.
- Don't know: leave the claim alone and mention it in the note. If it's
  important, mark it as unconfirmed in the body.

Also answer any existing `open_questions` on the concept the same way.

**Autonomous.** Don't ask. Add a self-contained question for each fact you
couldn't confirm to `open_questions`, then set the outcome to `partial` or
`unverifiable`, with a note that says the questions are queued. Don't
change those facts and don't add `verified`. Don't duplicate a question
that's already queued. Don't deprecate or delete anything just because it
couldn't be confirmed.

```yaml
open_questions:
  - "Is the team still on the annual support contract with the CI vendor? (okf-review-oldest, 2026-10-24)"
```

Either way, stamping `reviewed` is deliberate. It moves the concept to the
back of the queue so one blocked concept doesn't stall every future run,
and the outcome and note keep it honest. Questions queued by autonomous
runs are answered later with `okf.py oldest --open-questions` in an
interactive session.

## 4. Write it up

1. Update the frontmatter per the table above, using the `okf.py`
   commands. If you corrected facts:
   - Edit the body, dating changed claims where it helps ("as of
     2026-10-24").
   - Add a `sources` entry for the live check (`okf.py source`, e.g.
     `--id live-20261024`, with what you ran as `--resource`).
   - Stamp `generated` (`okf.py stamp <concept> generated`).
   - If you changed `description`, update the listing in the folder's
     `index.md`.
   - If `stale_after` is set and has passed, or you re-verified the
     concept, move it forward by the span it covered before.
2. Add a root `log.md` entry under today's date. Single-quote the text so
   the shell leaves its backticks alone:
   ```
   okf.py log 'Reviewed `/infra/build-server.md` (outcome: partial): ...'
   ```
3. Publish: `okf.py publish -m "Review <concept>: <outcome>" <concept> log.md`,
   naming every file you changed (it commits only those, then pulls with
   rebase and pushes to `main`). If it reports lint errors
   you didn't cause, or a rebase conflict (it aborts the rebase and leaves
   the commit local), stop and tell the user.
4. Report to the user: which concept, the outcome, what changed, what
   couldn't be checked and why, any questions queued, and any problems
   found in the real system.
