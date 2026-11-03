<!-- okf-catalog:begin (managed by okf-catalog-template install/setup.py; edits between these markers are replaced on reinstall) -->
# Knowledge catalog

I keep catalogs of context (systems, projects, people, processes,
decisions) as Open Knowledge Format documents. At the start of every
session, a SessionStart hook names the catalog that applies to it (by the
directory the session works in), its owner, and the session id. Below,
"the catalog" means that one and `<catalog>` its path. Each catalog's
AGENTS.md defines its conventions. If no catalog was named, these
instructions don't apply.

- Other sessions push to the catalog often. Run
  `git -C <catalog> pull --rebase origin main` before reading it, so you
  read the latest concepts.
- Never edit the main checkout. To write, run
  `python3 <catalog>/tools/okf.py session start --id <your session id>`;
  it prints your own worktree. Edit there, use that worktree's
  `tools/okf.py`, publish from it, and run `session end --id <id>` when
  done.
- Before working on something within the catalog's scope, check it for an
  existing concept and use it as context, unless a greenfield notice is
  active for the current work; then use the catalog only when I ask.
- When a session establishes something durable (how a system is built or
  reached, a root cause, a fix, a config change, a decision), add or update
  the matching concept there, following AGENTS.md: update the index.md and
  log.md, set `generated`, and cite sources.
- Record changes you make to real systems as one dated line in the
  affected concept (its new current truth) plus a `log.md` entry with the
  details, not as a narrative or change-log section. Before adding a
  section to a concept, ask whether it's about that concept or about
  something that runs on it or happened to it (an incident, a fix
  procedure, another system); those get their own concepts, linked from
  the hub. See AGENTS.md.
- When you find a bug or weakness and we decide not to fix it in this
  session (I say to leave it, it's out of scope, or it needs my decision),
  add it to `/projects/things-to-fix.md`: what's wrong, why it matters,
  where it lives, a possible fix, the date, and a link to the concept with
  the detail. Don't add what you fix in the same session; record that fix
  in the affected concept instead. When an entry gets fixed, remove it.
  Whenever you add an entry, say so in your reply.
- Never write secrets into the catalog.
- Every timestamp you write (`generated.at`, `verified[].at`, `reviewed.at`,
  log entries, "as of" notes) must come from the clock, via
  `date -u +%Y-%m-%dT%H:%M:%SZ` at the time of writing. Never guess or round
  to a plausible time. If the catalog records a reference time server for
  the network, the clock should agree with it. A timestamp in the future, or
  a clock that disagrees with that server, is an anomaly: investigate it,
  and record what you find in the catalog.
- Use `python3 <catalog>/tools/okf.py` for the catalog's bookkeeping
  instead of hand edits: `stamp`/`review`/`source` for frontmatter (it
  writes the real UTC time itself), `log` and `index` for log.md and
  index.md, `lint` to check, and `publish -m MSG PATH...` to commit only the
  files you changed, pull --rebase and push. Edit body prose with your
  normal tools. See the Tooling section of AGENTS.md.
- After updating the catalog, commit, then `pull --rebase origin main` again
  and push to `main` without asking. I can revert anything I don't want. If
  the pull fails or conflicts, stop and tell me instead of forcing it.

# Memory

The catalog is your primary long-term memory, in addition to any built-in
memory store.

- Whenever you decide something is worth remembering, record it in the
  catalog first: add or update the matching concept. This covers anything
  you'd otherwise save to Claude Code's memory directory
  (`~/.claude/projects/*/memory/`) or another memory tool. Then also save
  it to that store if it helps recall there; never save it only there.
- Everything maps to a concept:
  - facts about systems, projects, people and decisions go in their
    concept;
  - facts about me, and how I want you to work (corrections, preferences,
    approaches I've confirmed), go in `/people/<owner>.md`, created if
    missing;
  - pointers to external resources go in the concept they're about.
- What doesn't belong anywhere: secrets, things that only matter to the
  current conversation, and things outside the catalog's scope (another
  catalog on the machine may be the right home; ask).
- When recalling, check the catalog as well as your memory store, and
  prefer the catalog when they disagree; it's the one that gets reviewed.
<!-- okf-catalog:end -->
