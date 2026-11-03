#!/usr/bin/env python3
"""PostToolUse hook: when Claude saves a memory, make sure it reaches the catalog.

Fires after a Write/Edit into a Claude Code memory directory
(~/.claude/projects/*/memory/, except the MEMORY.md index) or a call to one
of the `memory_tools` listed in ~/.claude/okf-catalogs.json. If the current
turn hasn't touched the session's knowledge catalog, it quietly adds context
telling Claude to record the same fact there. Never blocks, and prints
nothing otherwise.
"""
import json
import os
import re
import sys

import okf_catalogs

MEMORY_DIR = re.compile(r"/\.claude/projects/[^/]+/memory/(?!MEMORY\.md$)[^/]+\.md$")


def current_turn_tool_uses(transcript_path):
    uses = []
    with open(transcript_path) as f:
        for line in f:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            content = (entry.get("message") or {}).get("content")
            if entry.get("type") == "user":
                # A real prompt (not a tool result) starts a new turn.
                if isinstance(content, str) or (
                    isinstance(content, list)
                    and not any(isinstance(c, dict) and c.get("type") == "tool_result" for c in content)
                ):
                    uses = []
            elif entry.get("type") == "assistant" and isinstance(content, list):
                uses.extend(c for c in content if isinstance(c, dict) and c.get("type") == "tool_use")
    return uses


def main():
    data = json.load(sys.stdin)
    catalogs, config = okf_catalogs.load()
    catalog = okf_catalogs.select(data.get("cwd"), catalogs)
    if not catalog:
        return
    tool = data.get("tool_name", "")
    tool_input = data.get("tool_input") or {}
    if tool in set(config.get("memory_tools") or []):
        what = tool
    elif tool in ("Write", "Edit") and MEMORY_DIR.search(tool_input.get("file_path", "")):
        what = tool_input["file_path"]
    else:
        return

    transcript = data.get("transcript_path")
    if transcript and os.path.exists(transcript):
        if any(okf_catalogs.mentions(catalog, u.get("input", {})) for u in current_turn_tool_uses(transcript)):
            return

    owner = catalog["owner"]
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": (
                f"You just saved a memory ({what}). The knowledge catalog at {catalog['path']} is the "
                "primary memory store: record the same fact there too, in the matching concept "
                f"(facts about {owner} and how they want you to work go in {catalog['owner_concept']}), "
                "using tools/okf.py for stamping, log, index and publish. Skip it only if the "
                "fact is a secret, already in the catalog, or outside the catalog's scope "
                f"({catalog['scope']})."
            ),
        }
    }))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # never break a session over a reminder
