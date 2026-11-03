"""Shared by the okf-* hooks: which knowledge catalog applies to a session.

The catalogs on this machine are listed in ~/.claude/okf-catalogs.json:

    {
      "catalogs": [
        {
          "name": "work",
          "path": "~/repos/acme-knowledge",
          "owner": "jdoe",
          "scope": "my work at Acme",
          "projects": ["~/work", "~/repos/acme-*"],
          "default": true
        }
      ],
      "memory_tools": ["mcp__memory__save_memory"],
      "greenfield_skills": ["superpowers:brainstorming", "superpowers:writing-plans"]
    }

A session belongs to the catalog it is working inside, else to the catalog
whose `projects` entry matches its working directory most specifically (an
entry matches the directory itself and everything under it, and may use
shell wildcards), else to the catalog marked `"default": true`, else to none.

`greenfield_skills` lists the skills that start greenfield (okf-greenfield.py):
the session is told not to consult the catalog or memory stores unless asked,
and to keep the owner's private details out of what it writes. Absent, a
default list applies; an empty list turns the notice off.
"""
import fnmatch
import json
import os

CONFIG = os.path.expanduser("~/.claude/okf-catalogs.json")

DEFAULT_GREENFIELD_SKILLS = [
    "superpowers:brainstorming",
    "superpowers:writing-plans",
    "superpowers:executing-plans",
    "superpowers:subagent-driven-development",
    # Deprecated aliases of the above.
    "superpowers:brainstorm",
    "superpowers:write-plan",
    "superpowers:execute-plan",
]


def _expand(path):
    return os.path.realpath(os.path.expanduser(path))


def read_config():
    """The parsed ~/.claude/okf-catalogs.json, or {} if it's missing, unreadable or not an object."""
    try:
        with open(CONFIG) as f:
            config = json.load(f)
    except (OSError, ValueError):
        return {}
    return config if isinstance(config, dict) else {}


def load():
    """Return (catalogs, config); catalogs whose path doesn't exist are dropped."""
    config = read_config()
    if not config:
        return [], {}
    catalogs = []
    for c in config.get("catalogs") or []:
        if not c.get("path"):
            continue
        c = dict(c)
        c["raw_path"] = c["path"]
        c["path"] = _expand(c["path"])
        c.setdefault("name", os.path.basename(c["path"]))
        c.setdefault("owner", "the owner")
        c.setdefault("owner_concept", f"/people/{c['owner']}.md")
        c.setdefault("scope", "the owner's world")
        if os.path.isdir(c["path"]):
            catalogs.append(c)
    return catalogs, config


def _inside(path, root):
    return path == root or path.startswith(root + os.sep)


def select(cwd, catalogs):
    """The catalog for a session working in cwd, or None."""
    cwd = _expand(cwd or os.getcwd())
    for c in catalogs:
        if _inside(cwd, c["path"]):
            return c
    best, best_len = None, -1
    for c in catalogs:
        for pattern in c.get("projects") or []:
            pattern = _expand(pattern)
            # Match the directory itself or any ancestor of cwd.
            probe = cwd
            while True:
                if fnmatch.fnmatch(probe, pattern):
                    if len(pattern) > best_len:
                        best, best_len = c, len(pattern)
                    break
                parent = os.path.dirname(probe)
                if parent == probe:
                    break
                probe = parent
    if best:
        return best
    return next((c for c in catalogs if c.get("default")), None)


def mentions(catalog, payload):
    """Whether a tool input (any JSON-able value) refers to the catalog."""
    text = json.dumps(payload)
    names = {catalog["path"], catalog["raw_path"], os.path.basename(catalog["path"])}
    return any(n and n in text for n in names)


def greenfield_skills(config):
    """The skills that start greenfield: the configured list, else the default."""
    skills = config.get("greenfield_skills") if isinstance(config, dict) else None
    if not isinstance(skills, list):
        return list(DEFAULT_GREENFIELD_SKILLS)
    return [s for s in skills if isinstance(s, str)]
