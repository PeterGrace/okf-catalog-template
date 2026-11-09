#!/usr/bin/env python3
"""Stop and SessionEnd hook: nudge Claude to record durable knowledge in the OKF catalog.

A turn "touches real systems" when it runs Bash commands that reach or change
hosts, clusters, routers or packages, or MCP tools that change things.
Ordinary coding turns (edits, tests, git, reads) never count.

Every reminder costs a whole extra model call that re-reads the session's
context, so on Stop the hook batches: it counts the turns that touched real
systems since the catalog was last touched (or the last reminder), and blocks
the stop with a reminder only when

- that count reaches OKF_REMINDER_TURNS (default 3), or
- the oldest of those turns is OKF_REMINDER_MINUTES old (default 20), or
- the context has grown past OKF_REMINDER_CONTEXT tokens (default 150000),
  just before compaction would lose the detail; this fires once on crossing
  the threshold and again for every further 100000 tokens.

A turn that touches the session's catalog clears the count. The count lives in
a per-session state file in OKF_REMINDER_STATE_DIR (default
~/.claude/okf-reminder/). The hook stays silent inside a catalog itself, on
the re-entry after a reminder (stop_hook_active), and when no catalog applies
to the session. A blocked stop always shows up as "Stop hook error" in the UI.

On SessionEnd, a session that still has unrecorded turns gets one line in
unrecorded.jsonl in the state directory (session id, cwd, transcript, count),
so a later session can follow up; Claude can no longer act at that point.

Saving a memory is handled separately by okf-memory-mirror.py.
"""
import json
import os
import re
import sys
import time

import okf_catalogs

SYSTEM_COMMAND = re.compile(
    r"(?:^|[\s;&|(`$])(?:sudo\s+)?"
    r"(ssh|scp|rsync|kubectl|helm|argocd|vtysh|systemctl|iptables|ip6tables|nft|ufw|"
    r"wg|virsh|terraform|ansible|ansible-playbook|apt|apt-get|dnf|pkg|opnsense-update|"
    r"docker|podman|crontab|aws|gcloud|az)\b"
)
GH_WRITE = re.compile(r"\bgh\s+api\b.*\s(-X|--method)\s+(POST|PUT|PATCH|DELETE)", re.S)
MCP_READ_ONLY = re.compile(
    r"__(get|list|search|query|read|trace|audit|inspect|measure|screenshot|describe|running|crash)"
)
CONTEXT_STEP = 100_000
STATE_MAX_AGE = 7 * 86400  # state files of sessions that never ended cleanly


def setting(name, default):
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def state_dir():
    return os.path.expanduser(os.environ.get("OKF_REMINDER_STATE_DIR") or "~/.claude/okf-reminder")


def state_path(session_id):
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", session_id or "unknown")
    return os.path.join(state_dir(), f"{safe}.json")


def load_state(session_id):
    try:
        with open(state_path(session_id)) as f:
            state = json.load(f)
        return state if isinstance(state, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(session_id, state):
    os.makedirs(state_dir(), exist_ok=True)
    path = state_path(session_id)
    with open(path + ".tmp", "w") as f:
        json.dump(state, f)
    os.replace(path + ".tmp", path)


def prune_states(now):
    try:
        names = os.listdir(state_dir())
    except OSError:
        return
    for name in names:
        path = os.path.join(state_dir(), name)
        if name.endswith(".json"):
            try:
                if now - os.path.getmtime(path) > STATE_MAX_AGE:
                    os.remove(path)
            except OSError:
                pass


def last_turn(transcript_path):
    """The last turn's id (its prompt's uuid), its tool uses, and the context size in tokens."""
    turn_id, uses, context = None, [], 0
    with open(transcript_path) as f:
        for line in f:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            message = entry.get("message") or {}
            content = message.get("content")
            if entry.get("type") == "user":
                # A real prompt (not a tool result) starts a new turn.
                if isinstance(content, str) or (
                    isinstance(content, list)
                    and not any(isinstance(c, dict) and c.get("type") == "tool_result" for c in content)
                ):
                    turn_id, uses = entry.get("uuid"), []
            elif entry.get("type") == "assistant":
                if isinstance(content, list):
                    uses.extend(c for c in content if isinstance(c, dict) and c.get("type") == "tool_use")
                usage = message.get("usage")
                if isinstance(usage, dict):
                    context = sum(usage.get(k) or 0 for k in
                                  ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
    return turn_id, uses, context


def touches_real_systems(use):
    name = use.get("name", "")
    if name == "Bash":
        cmd = (use.get("input") or {}).get("command", "")
        return bool(SYSTEM_COMMAND.search(cmd) or GH_WRITE.search(cmd))
    if name.startswith("mcp__"):
        return not MCP_READ_ONLY.search(name.lower())
    return False


def touches_catalog(catalog, use):
    return okf_catalogs.touches(catalog, use)


def write_hint(catalog):
    return f"{okf_catalogs.how_to_write(catalog)}, following its AGENTS.md"


def session_catalog(data):
    catalogs, _ = okf_catalogs.load()
    cwd = os.path.realpath(data.get("cwd") or os.getcwd())
    if any((cwd == c["path"] or cwd.startswith(c["path"] + os.sep)) and not okf_catalogs.served(c)
           for c in catalogs):
        return None
    return okf_catalogs.select(cwd, catalogs)


def update(state, turn_id, touched_systems, touched_catalog, context, now):
    """Fold one finished turn into the state; return the reason to remind, or None."""
    if turn_id is not None and turn_id == state.get("last_turn"):
        return None  # this turn was already counted
    state["last_turn"] = turn_id
    state["context"] = context
    if touched_catalog:
        state["pending"], state["since"] = 0, None
        return None
    if touched_systems:
        state["pending"] = state.get("pending", 0) + 1
        state["since"] = state.get("since") or now
    if not state.get("pending"):
        return None

    limit = setting("OKF_REMINDER_CONTEXT", 150_000)
    mark = state.get("context_mark")
    if context < limit:
        mark = state["context_mark"] = None  # below the limit, or compacted: start over
    if context >= limit and (mark is None or context >= mark + CONTEXT_STEP):
        reason = f"the context has reached about {context // 1000}k tokens"
        state["context_mark"] = context
    elif state["pending"] >= setting("OKF_REMINDER_TURNS", 3):
        reason = f"{state['pending']} turns touched real systems"
    elif now - state["since"] >= setting("OKF_REMINDER_MINUTES", 20) * 60:
        reason = f"turns have touched real systems for {int(now - state['since']) // 60} minutes"
    else:
        return None
    state["pending"], state["since"] = 0, None
    return reason


def on_stop(data, now):
    if data.get("stop_hook_active"):
        return
    catalog = session_catalog(data)
    if not catalog:
        return
    transcript = data.get("transcript_path")
    if not transcript or not os.path.exists(transcript):
        return
    turn_id, uses, context = last_turn(transcript)
    session_id = data.get("session_id")
    state = load_state(session_id)
    reason = update(state, turn_id,
                    any(touches_real_systems(u) for u in uses),
                    any(touches_catalog(catalog, u) for u in uses),
                    context, now)
    save_state(session_id, state)
    prune_states(now)
    if not reason:
        return
    print(json.dumps({
        "decision": "block",
        "reason": (
            f"OKF catalog check ({reason}): turns since the catalog was last updated touched "
            "real systems. If those turns "
            f"established durable knowledge within the catalog's scope ({catalog['scope']}): how a "
            "system is built or reached, a root cause, a fix, a config change made to a real "
            f"system, a decision, record it in {write_hint(catalog)}. If nothing durable was "
            "established, stop without mentioning this check."
        ),
    }))


def on_session_end(data, now):
    session_id = data.get("session_id")
    state = load_state(session_id)
    pending = state.get("pending") or 0
    if pending:
        os.makedirs(state_dir(), exist_ok=True)
        with open(os.path.join(state_dir(), "unrecorded.jsonl"), "a") as f:
            f.write(json.dumps({
                "ended": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
                "session_id": session_id,
                "cwd": data.get("cwd"),
                "transcript_path": data.get("transcript_path"),
                "reason": data.get("reason"),
                "pending_turns": pending,
            }) + "\n")
    try:
        os.remove(state_path(session_id))
    except OSError:
        pass


def main():
    data = json.load(sys.stdin)
    now = time.time()
    if data.get("hook_event_name") == "SessionEnd":
        on_session_end(data, now)
    else:
        on_stop(data, now)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # never break a session over a reminder
