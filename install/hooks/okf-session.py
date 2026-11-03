#!/usr/bin/env python3
"""SessionStart hook: tell the session which catalog applies and which worktree is its own.

Each Claude Code session that writes to a knowledge catalog does it in its
own git worktree (.worktrees/<session_id>), so sessions never share a working
tree. This picks the catalog for the session's working directory (see
okf_catalogs.py), and injects its path, the session id and the command that
creates or reuses the worktree. It runs again after /clear, resume and
compaction, so the id survives a compacted context. It never creates
anything itself.
"""
import json
import re
import sys

import okf_catalogs


def main():
    data = json.load(sys.stdin)
    sid = re.sub(r"[^A-Za-z0-9_-]", "", data.get("session_id") or "")
    catalogs, _ = okf_catalogs.load()
    catalog = okf_catalogs.select(data.get("cwd"), catalogs)
    if not sid or not catalog:
        return
    path = catalog["path"]
    okf = f"python3 {path}/tools/okf.py"
    context = (
        f"Knowledge catalog for this session: {path} (\"{catalog['name']}\", covering "
        f"{catalog['scope']}; owner {catalog['owner']}). It is the one the catalog instructions "
        f"in CLAUDE.md refer to. Session id: {sid}. To write to the catalog, first run "
        f"`{okf} session start --id {sid}`; it prints your own worktree path "
        f"({path}/.worktrees/{sid}). Make every catalog edit there, run that "
        "worktree's tools/okf.py, and publish from it with `publish -m MSG PATH...`. "
        "Never edit the main checkout. When you're done with the catalog, run "
        f"`{okf} session end --id {sid}`."
    )
    others = [c for c in catalogs if c is not catalog]
    if others:
        context += (
            " Other catalogs on this machine, which you may read for context but don't "
            "write to unless the user asks: "
            + "; ".join(f"{c['path']} (\"{c['name']}\", {c['scope']})" for c in others)
            + "."
        )
    print(json.dumps({
        "hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context}
    }))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # never break a session over a reminder
