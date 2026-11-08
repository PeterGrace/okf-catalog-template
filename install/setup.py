#!/usr/bin/env python3
"""Set up a knowledge catalog cloned from okf-catalog-template.

    python3 install/setup.py init --owner jdoe --scope "my work at Acme" [--name "Acme knowledge"]
    python3 install/setup.py install [--projects ~/work ~/repos/acme-*] [--default]
    python3 install/setup.py status

`init` runs once, in a fresh clone: it fills in the {{...}} placeholders in
the repository machinery, puts the starter concepts in place and records
the catalog's identity in .okf-catalog.json. Commit and push the result.

`install` runs on every machine that should use this catalog. It
  - copies the hooks to ~/.claude/hooks/ (keeping a .bak of any older copy),
  - registers this catalog in ~/.claude/okf-catalogs.json, with the project
    directories it covers (--projects) and whether it is the fallback for
    sessions anywhere else (--default),
  - adds the hooks to ~/.claude/settings.json without touching other entries,
  - writes the catalog instructions into ~/.claude/CLAUDE.md between
    okf-catalog markers, replacing an older copy of the same block.
Running it again is safe. Several catalogs can be installed on one machine;
each session uses the one that covers its working directory.

Standard library only.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone

REPO = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
INSTALL = os.path.join(REPO, "install")
IDENTITY = os.path.join(REPO, ".okf-catalog.json")
CLAUDE_DIR = os.path.expanduser("~/.claude")
HOOKS_DIR = os.path.join(CLAUDE_DIR, "hooks")
CATALOGS = os.path.join(CLAUDE_DIR, "okf-catalogs.json")
SETTINGS = os.path.join(CLAUDE_DIR, "settings.json")
CLAUDE_MD = os.path.join(CLAUDE_DIR, "CLAUDE.md")

# Files whose {{...}} placeholders init fills in.
TEMPLATED = ["AGENTS.md", "tools/okf.py", ".claude/skills/okf-link-check/SKILL.md",
             ".claude/skills/okf-review-oldest/SKILL.md", ".claude/skills/okf-reorganize/SKILL.md"]
HOOKS = [  # (event, matcher, script); a script may serve several events
    ("SessionStart", None, "okf-session.py"),
    ("PostToolUse", "Write|Edit", "okf-memory-mirror.py"),
    ("PostToolUse", "Skill", "okf-greenfield.py"),
    ("UserPromptSubmit", None, "okf-greenfield.py"),
    ("Stop", None, "okf-reminder.py"),
    ("SessionEnd", None, "okf-reminder.py"),
]
BEGIN, END = "<!-- okf-catalog:begin", "<!-- okf-catalog:end -->"


def die(msg):
    sys.exit(f"setup: {msg}")


def tilde(path):
    home = os.path.expanduser("~")
    return "~" + path[len(home):] if path == home or path.startswith(home + os.sep) else path


def catalog_path():
    """The catalog's main checkout, even when this runs from a session worktree.

    REPO is where these files are read and written; this is the path recorded
    in the instructions and in ~/.claude/okf-catalogs.json.
    """
    try:
        common = subprocess.run(["git", "-C", REPO, "rev-parse", "--path-format=absolute", "--git-common-dir"],
                                capture_output=True, text=True).stdout.strip()
    except OSError:
        common = ""
    return os.path.dirname(os.path.realpath(common)) if common else REPO


def fill(text, values):
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def cmd_init(a):
    if os.path.exists(IDENTITY):
        die(f"already initialized ({IDENTITY} exists)")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", a.owner):
        die("--owner must be a short id usable as a filename, e.g. jdoe")
    now = datetime.now(timezone.utc)
    values = {
        "CATALOG": tilde(catalog_path()),
        "OWNER": a.owner,
        "SCOPE": a.scope,
        "NAME": a.name or "Knowledge Catalog",
        "NOW": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "DATE": now.strftime("%Y-%m-%d"),
    }
    for rel in TEMPLATED:
        path = os.path.join(REPO, rel)
        with open(path) as f:
            text = f.read()
        with open(path, "w") as f:
            f.write(fill(text, values))
        print(f"filled {rel}")
    skeleton = os.path.join(INSTALL, "skeleton")
    for dirpath, _, files in os.walk(skeleton):
        for name in files:
            src = os.path.join(dirpath, name)
            rel = os.path.relpath(src, skeleton).replace("OWNER.md", f"{a.owner}.md")
            dst = os.path.join(REPO, rel)
            if os.path.exists(dst):
                print(f"kept existing {rel}")
                continue
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(src) as f:
                text = f.read()
            with open(dst, "w") as f:
                f.write(fill(text, values))
            print(f"created {rel}")
    identity = {"name": values["NAME"], "owner": a.owner, "scope": a.scope}
    with open(IDENTITY, "w") as f:
        json.dump(identity, f, indent=2)
        f.write("\n")
    print(f"wrote .okf-catalog.json\n\nNext: review, commit and push, then run "
          f"`python3 {tilde(catalog_path())}/install/setup.py install` on each machine.")


def load_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except ValueError as e:
        die(f"{path} isn't valid JSON ({e}); fix it first")


def save_json(path, data):
    if os.path.exists(path):
        shutil.copy2(path, path + ".bak")
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def install_hooks():
    os.makedirs(HOOKS_DIR, exist_ok=True)
    src_dir = os.path.join(INSTALL, "hooks")
    for name in sorted(os.listdir(src_dir)):
        if not name.endswith(".py"):
            continue
        src, dst = os.path.join(src_dir, name), os.path.join(HOOKS_DIR, name)
        with open(src, "rb") as f:
            new = f.read()
        if os.path.exists(dst):
            with open(dst, "rb") as f:
                if f.read() == new:
                    continue
            shutil.copy2(dst, dst + ".bak")
        shutil.copy2(src, dst)
        os.chmod(dst, 0o755)
        print(f"hook {tilde(dst)} installed")


def register(a):
    identity = load_json(IDENTITY, None)
    if not identity:
        die("this catalog isn't initialized; run `setup.py init` first")
    path = catalog_path()
    config = load_json(CATALOGS, {"catalogs": []})
    catalogs = config.setdefault("catalogs", [])
    entry = next((c for c in catalogs if os.path.realpath(os.path.expanduser(c.get("path", ""))) == path), None)
    if entry is None:
        entry = {"path": tilde(path)}
        catalogs.append(entry)
    entry.update({k: identity[k] for k in ("name", "owner", "scope")})
    if a.projects is not None:
        entry["projects"] = [tilde(os.path.abspath(os.path.expanduser(p))) if "*" not in p else p
                             for p in a.projects]
    else:
        entry.setdefault("projects", [])
    if a.default or len(catalogs) == 1:
        for c in catalogs:
            c.pop("default", None)
        entry["default"] = True
    if a.memory_tool:
        tools = config.setdefault("memory_tools", [])
        tools.extend(t for t in a.memory_tool if t not in tools)
    save_json(CATALOGS, config)
    print(f"registered {tilde(path)} in {tilde(CATALOGS)}"
          + (" (default)" if entry.get("default") else ""))
    return config


def merge_settings(config):
    settings = load_json(SETTINGS, {})
    hooks = settings.setdefault("hooks", {})
    changed = False
    for event, matcher, script in HOOKS:
        if script == "okf-memory-mirror.py":
            matcher = "|".join(["Write", "Edit"] + (config.get("memory_tools") or []))
        command = f"~/.claude/hooks/{script}"
        groups = hooks.setdefault(event, [])
        existing = next((g for g in groups for h in g.get("hooks", []) if h.get("command") == command), None)
        if existing is not None:
            if matcher and existing.get("matcher") != matcher:
                existing["matcher"] = matcher
                changed = True
            continue
        group = {"hooks": [{"type": "command", "command": command, "timeout": 10}]}
        if matcher:
            group["matcher"] = matcher
        groups.append(group)
        changed = True
    if changed:
        save_json(SETTINGS, settings)
        print(f"hooks added to {tilde(SETTINGS)}")


def write_claude_md():
    with open(os.path.join(INSTALL, "CLAUDE-block.md")) as f:
        block = f.read().strip() + "\n"
    try:
        with open(CLAUDE_MD) as f:
            text = f.read()
    except FileNotFoundError:
        text = ""
    start, end = text.find(BEGIN), text.find(END)
    if start != -1 and end != -1:
        new = text[:start] + block + text[end + len(END):].lstrip("\n")
    elif re.search(r"^# Knowledge catalog\s*$", text, re.M):
        print(f"{tilde(CLAUDE_MD)} has an unmarked '# Knowledge catalog' section, probably an older "
              "hand-written copy. Remove it (and its '# Memory' section), then run install again; "
              "CLAUDE.md left unchanged.")
        return
    else:
        new = (text.rstrip("\n") + "\n\n" if text.strip() else "") + block
    if new != text:
        if text:
            shutil.copy2(CLAUDE_MD, CLAUDE_MD + ".bak")
        with open(CLAUDE_MD, "w") as f:
            f.write(new)
        print(f"catalog instructions written to {tilde(CLAUDE_MD)}")


def cmd_install(a):
    install_hooks()
    config = register(a)
    merge_settings(config)
    write_claude_md()
    print("\nDone. New Claude Code sessions pick it up; restart running ones (or open /hooks once).")


def cmd_status(a):
    sys.path.insert(0, HOOKS_DIR)
    try:
        import okf_catalogs
    except ImportError:
        die("hooks aren't installed on this machine; run `setup.py install`")
    catalogs, _ = okf_catalogs.load()
    for c in catalogs:
        print(f"{'*' if c.get('default') else ' '} {c['name']}: {tilde(c['path'])} "
              f"(owner {c['owner']}; {c['scope']}) projects={c.get('projects') or []}")
    cwd = a.cwd or os.getcwd()
    chosen = okf_catalogs.select(cwd, catalogs)
    print(f"\nA session in {tilde(os.path.abspath(cwd))} uses: {chosen['name'] if chosen else 'no catalog'}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init", help="fill in placeholders and create the starter concepts (once, in a fresh clone)")
    p.add_argument("--owner", required=True, help="owner id, e.g. jdoe; also names /people/<owner>.md")
    p.add_argument("--scope", required=True, help='what the catalog covers, e.g. "my work at Acme"')
    p.add_argument("--name", help='catalog title, e.g. "Acme knowledge catalog"')
    p.set_defaults(fn=cmd_init)
    p = sub.add_parser("install", help="wire this machine's Claude Code up to this catalog")
    p.add_argument("--projects", nargs="*", metavar="DIR",
                   help="directories (shell wildcards allowed) whose sessions use this catalog")
    p.add_argument("--default", action="store_true",
                   help="use this catalog for sessions that no catalog's --projects cover")
    p.add_argument("--memory-tool", nargs="*", metavar="TOOL",
                   help="MCP memory tools to mirror into the catalog, e.g. mcp__memory__save_memory")
    p.set_defaults(fn=cmd_install)
    p = sub.add_parser("status", help="list installed catalogs and which one a directory uses")
    p.add_argument("cwd", nargs="?", help="directory to check (default: current)")
    p.set_defaults(fn=cmd_status)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
