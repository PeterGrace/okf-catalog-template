#!/usr/bin/env python3
"""Stop hook: nudge Claude to record durable knowledge in the OKF catalog.

Blocks the stop (with a reminder) whenever the turn that just ended touched
real systems: Bash commands that reach or change hosts, clusters, routers or
packages, or MCP tools that change things. Ordinary coding turns (edits,
tests, git, reads) stay silent, since a blocked stop always shows up as
"Stop hook error" in the UI. Also silent inside a catalog itself, when the
turn already touched the session's catalog, on the re-entry after a reminder
(stop_hook_active), and when no catalog applies to the session. Saving a
memory is handled separately by okf-memory-mirror.py.
"""
import json
import os
import re
import sys

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


def last_turn_tool_uses(transcript_path):
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


def touches_real_systems(use):
    name = use.get("name", "")
    if name == "Bash":
        cmd = (use.get("input") or {}).get("command", "")
        return bool(SYSTEM_COMMAND.search(cmd) or GH_WRITE.search(cmd))
    if name.startswith("mcp__"):
        return not MCP_READ_ONLY.search(name.lower())
    return False


def main():
    data = json.load(sys.stdin)
    if data.get("stop_hook_active"):
        return
    catalogs, _ = okf_catalogs.load()
    cwd = os.path.realpath(data.get("cwd") or os.getcwd())
    if any(cwd == c["path"] or cwd.startswith(c["path"] + os.sep) for c in catalogs):
        return
    catalog = okf_catalogs.select(cwd, catalogs)
    if not catalog:
        return
    transcript = data.get("transcript_path")
    if not transcript or not os.path.exists(transcript):
        return

    uses = last_turn_tool_uses(transcript)
    if not any(touches_real_systems(u) for u in uses):
        return
    if any(okf_catalogs.mentions(catalog, u.get("input", {})) for u in uses):
        return

    print(json.dumps({
        "decision": "block",
        "reason": (
            "OKF catalog check: this turn touched real systems. If it established durable "
            f"knowledge within the catalog's scope ({catalog['scope']}): how a system is built or "
            "reached, a root cause, a fix, a config change made to a real system, a decision, "
            f"record it in {catalog['path']} following its AGENTS.md, using tools/okf.py for "
            "stamping, log, index and publish. If nothing durable was established, stop without "
            "mentioning this check."
        ),
    }))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # never break a session over a reminder
