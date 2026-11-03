#!/usr/bin/env python3
"""PostToolUse and UserPromptSubmit hook: start design and planning work greenfield.

When a skill listed in `greenfield_skills` (~/.claude/okf-catalogs.json, or
the default in okf_catalogs.py) is loaded through the Skill tool, or typed as
a /slash command, this adds context telling the session not to consult the
knowledge catalog or memory stores unless the user asks, and to keep what it
already knows about the owner's systems out of everything it writes. Designs
and plans often end up in public repositories. Fires in every repository and
whether or not a catalog applies to the session. Never blocks, and prints
nothing otherwise.
"""
import json
import re
import sys

import okf_catalogs

NOTICE = (
    "Greenfield: `{skill}` is running. For this work, don't read the knowledge catalog or "
    "any memory store (memory MCP tools, ~/.claude/projects/*/memory) unless the user asks "
    "in this conversation. Keep anything you already know about the owner's systems out of "
    "every file and commit message you write (specs, plans, code, tests, fixtures): no real "
    "hostnames, domains, registries, cluster or repository names, IP addresses, or personal "
    "names and email addresses. Use placeholders such as example.com and example.internal. "
    "When you dispatch subagents, include this rule in their prompts."
)


def invoked_skill(data, skills):
    """The listed skill this hook event starts, or None."""
    event = data.get("hook_event_name")
    if event == "PostToolUse" and data.get("tool_name") == "Skill":
        ti = data.get("tool_input")
        name = ti.get("skill") if isinstance(ti, dict) else None
        return name if isinstance(name, str) and name in skills else None
    if event == "UserPromptSubmit" and isinstance(data.get("prompt"), str):
        m = re.match(r"\s*/(\S+)", data["prompt"])
        return m.group(1) if m and m.group(1) in skills else None
    return None


def main():
    data = json.load(sys.stdin)
    if not isinstance(data, dict):
        return
    config = okf_catalogs.read_config()
    skill = invoked_skill(data, set(okf_catalogs.greenfield_skills(config)))
    if not skill:
        return
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": data["hook_event_name"],
            "additionalContext": NOTICE.format(skill=skill),
        }
    }))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # never break a session over a reminder
