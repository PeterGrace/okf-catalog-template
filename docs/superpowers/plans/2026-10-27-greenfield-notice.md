# Greenfield Notice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Greenfield rule for this work:** don't consult any knowledge catalog or memory store, and don't write real hostnames, domains, registries, cluster or repository names, IP addresses, or personal names and emails into any file or commit message. Use `example.com` / `example.internal` style placeholders. Pass this rule on to every subagent.

**Goal:** When a listed design or planning skill runs, inject a "greenfield" notice telling the session not to consult the catalog or memory stores unless asked, and to keep the owner's private details out of everything it writes.

**Architecture:** A new hook script, `install/hooks/okf-greenfield.py`, runs on PostToolUse (matcher `Skill`) and UserPromptSubmit. It reads the skill list from `~/.claude/okf-catalogs.json` through a new helper in `okf_catalogs.py` and prints `additionalContext` when the skill is listed. `setup.py` learns to register more than one script per event. Docs and the CLAUDE.md block are updated to match. First, `okf.py` stops treating the template's own `docs/` and `tests/` as concepts.

**Tech Stack:** Python 3 standard library only (`json`, `re`, `subprocess`, `unittest`, `importlib`), Claude Code hooks.

**Spec:** `docs/superpowers/specs/2026-10-27-greenfield-notice-design.md`

---

## File structure

| File | Change | Responsibility |
|---|---|---|
| `tools/okf.py` | Modify | Skip top-level `docs/` and `tests/` when walking for concepts |
| `install/hooks/okf_catalogs.py` | Modify | `DEFAULT_GREENFIELD_SKILLS`, `greenfield_skills(config)` |
| `install/hooks/okf-greenfield.py` | Create | The hook: decide whether a listed skill started, print the notice |
| `install/setup.py` | Modify | `HOOKS` becomes a list of `(event, matcher, script)`; register the new hook twice |
| `install/CLAUDE-block.md` | Modify | Greenfield exception on the "check the catalog" bullet |
| `AGENTS.md`, `README.md` | Modify | Machinery list and hook list |
| `tests/test_okf_walk.py` | Create | `walk_md` skips `docs/` and `tests/` |
| `tests/test_greenfield.py` | Create | `greenfield_skills` and the hook script |
| `tests/test_setup_hooks.py` | Create | `merge_settings` registration and idempotence |

Run all tests from the repository root with:

```bash
python3 -m unittest discover -s tests -v
```

---

### Task 1: Keep the template's `docs/` and `tests/` out of the catalog

`okf.py lint` currently fails on this repository: it treats `docs/superpowers/specs/*.md` as concepts with no frontmatter. Top-level `docs/` and `tests/` are development material for the template, not concepts.

**Files:**
- Modify: `tools/okf.py:35` (constants), `tools/okf.py:598-603` (`walk_md`), `tools/okf.py:1502` (new-concept guard)
- Test: `tests/test_okf_walk.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_okf_walk.py`:

```python
import importlib.util
import os
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_okf():
    spec = importlib.util.spec_from_file_location("okf", os.path.join(REPO, "tools", "okf.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class WalkMdTest(unittest.TestCase):
    def test_skips_top_level_docs_and_tests_only(self):
        okf = load_okf()
        with tempfile.TemporaryDirectory() as root:
            for rel in ["docs/superpowers/specs/a.md", "tests/b.md", "infra/docs/c.md",
                        "infra/tests/d.md", "x.md"]:
                path = os.path.join(root, rel)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w") as f:
                    f.write("x\n")
            self.assertEqual(sorted(okf.walk_md(root)),
                             ["infra/docs/c.md", "infra/tests/d.md", "x.md"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `python3 -m unittest tests.test_okf_walk -v`
Expected: FAIL; the list also contains `docs/superpowers/specs/a.md` and `tests/b.md`.

- [ ] **Step 3: Implement**

In `tools/okf.py`, after the `SKIP_DIRS` line (line 35), add:

```python
SKIP_TOP = {"docs", "tests"}  # the template's own development docs and tests, at the root only
```

Replace `walk_md` with:

```python
def walk_md(root):
    for dirpath, dirnames, filenames in os.walk(root):
        top = os.path.normpath(dirpath) == os.path.normpath(root)
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")
                             and not (top and d in SKIP_TOP))
        for f in sorted(filenames):
            if f.endswith(".md"):
                yield os.path.relpath(os.path.join(dirpath, f), root)
```

In the new-concept guard (around line 1502), change:

```python
    if parts[0] in SKIP_DIRS | {"tools"} or any(x.startswith(".") for x in parts):
```

to:

```python
    if parts[0] in SKIP_DIRS | SKIP_TOP | {"tools"} or any(x.startswith(".") for x in parts):
```

- [ ] **Step 4: Run the test and lint**

Run: `python3 -m unittest tests.test_okf_walk -v`
Expected: PASS

Run: `python3 tools/okf.py lint; echo exit=$?`
Expected: no `docs/superpowers` errors; `exit=0`.

- [ ] **Step 5: Add `docs/` and `tests/` to the machinery list in `AGENTS.md`**

Replace:

```markdown
- **`AGENTS.md`, `CLAUDE.md`, `README.md`, `.claude/`, `tools/`,
  `install/`, `.okf-catalog.json`, `.gitignore`, `.gitattributes` and
  `.worktrees/` are repository machinery, not OKF concepts.** The markdown
```

with:

```markdown
- **`AGENTS.md`, `CLAUDE.md`, `README.md`, `.claude/`, `tools/`,
  `install/`, the top-level `docs/` and `tests/`, `.okf-catalog.json`,
  `.gitignore`, `.gitattributes` and `.worktrees/` are repository
  machinery, not OKF concepts.** The markdown
```

- [ ] **Step 6: Commit**

```bash
git add tools/okf.py tests/test_okf_walk.py AGENTS.md
git commit -m "okf.py: treat top-level docs/ and tests/ as machinery, not concepts

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: `greenfield_skills` in `okf_catalogs.py`

**Files:**
- Modify: `install/hooks/okf_catalogs.py` (docstring example, new constant and function)
- Test: `tests/test_greenfield.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_greenfield.py`:

```python
import json
import os
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOKS = os.path.join(REPO, "install", "hooks")
sys.path.insert(0, HOOKS)

import okf_catalogs  # noqa: E402


class GreenfieldSkillsTest(unittest.TestCase):
    def test_default_when_absent(self):
        self.assertEqual(okf_catalogs.greenfield_skills({}), okf_catalogs.DEFAULT_GREENFIELD_SKILLS)
        self.assertIn("superpowers:brainstorming", okf_catalogs.DEFAULT_GREENFIELD_SKILLS)

    def test_default_list_is_a_copy(self):
        okf_catalogs.greenfield_skills({}).append("x")
        self.assertNotIn("x", okf_catalogs.DEFAULT_GREENFIELD_SKILLS)

    def test_configured_list_wins(self):
        self.assertEqual(okf_catalogs.greenfield_skills({"greenfield_skills": ["a:b"]}), ["a:b"])

    def test_empty_list_disables(self):
        self.assertEqual(okf_catalogs.greenfield_skills({"greenfield_skills": []}), [])

    def test_bad_entries_ignored(self):
        self.assertEqual(okf_catalogs.greenfield_skills({"greenfield_skills": ["a:b", 3, None]}), ["a:b"])

    def test_not_a_list_means_default(self):
        self.assertEqual(okf_catalogs.greenfield_skills({"greenfield_skills": "a:b"}),
                         okf_catalogs.DEFAULT_GREENFIELD_SKILLS)
        self.assertEqual(okf_catalogs.greenfield_skills(None), okf_catalogs.DEFAULT_GREENFIELD_SKILLS)


if __name__ == "__main__":
    unittest.main()
```

(`json`, `subprocess` and `tempfile` are used by the hook tests added in Task 3.)

- [ ] **Step 2: Run it to make sure it fails**

Run: `python3 -m unittest tests.test_greenfield -v`
Expected: FAIL with `AttributeError: module 'okf_catalogs' has no attribute 'greenfield_skills'`.

- [ ] **Step 3: Implement**

In `install/hooks/okf_catalogs.py`, extend the docstring's config example. Replace:

```
      "memory_tools": ["<the existing example memory tool>"]
    }
```

with:

```
      "memory_tools": ["mcp__memory__save_memory"],
      "greenfield_skills": ["superpowers:brainstorming", "superpowers:writing-plans"]
    }
```

and append to the docstring, before its closing `"""`:

```
`greenfield_skills` lists the skills that start greenfield (okf-greenfield.py):
the session is told not to consult the catalog or memory stores unless asked,
and to keep the owner's private details out of what it writes. Absent, a
default list applies; an empty list turns the notice off.
```

After `CONFIG = ...`, add:

```python
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
```

At the end of the file, add:

```python
def greenfield_skills(config):
    """The skills that start greenfield: the configured list, else the default."""
    skills = config.get("greenfield_skills") if isinstance(config, dict) else None
    if not isinstance(skills, list):
        return list(DEFAULT_GREENFIELD_SKILLS)
    return [s for s in skills if isinstance(s, str)]
```

- [ ] **Step 4: Run the test to make sure it passes**

Run: `python3 -m unittest tests.test_greenfield -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add install/hooks/okf_catalogs.py tests/test_greenfield.py
git commit -m "okf_catalogs: greenfield_skills list with a default

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: The `okf-greenfield.py` hook

**Files:**
- Create: `install/hooks/okf-greenfield.py`
- Test: `tests/test_greenfield.py` (append a second test class)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_greenfield.py`, above the `if __name__ == "__main__":` line:

```python
SCRIPT = os.path.join(HOOKS, "okf-greenfield.py")


class GreenfieldHookTest(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        os.makedirs(os.path.join(self.home.name, ".claude"))

    def tearDown(self):
        self.home.cleanup()

    def config(self, data):
        with open(os.path.join(self.home.name, ".claude", "okf-catalogs.json"), "w") as f:
            f.write(data if isinstance(data, str) else json.dumps(data))

    def run_hook(self, payload):
        stdin = payload if isinstance(payload, str) else json.dumps(payload)
        proc = subprocess.run([sys.executable, SCRIPT], input=stdin, capture_output=True, text=True,
                              env={**os.environ, "HOME": self.home.name})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stderr, "")
        return json.loads(proc.stdout) if proc.stdout.strip() else None

    def skill(self, name):
        return {"hook_event_name": "PostToolUse", "tool_name": "Skill",
                "tool_input": {"skill": name}, "cwd": self.home.name}

    def prompt(self, text):
        return {"hook_event_name": "UserPromptSubmit", "prompt": text, "cwd": self.home.name}

    def assertNotice(self, out, event, skill):
        self.assertIsNotNone(out)
        hso = out["hookSpecificOutput"]
        self.assertEqual(hso["hookEventName"], event)
        self.assertTrue(hso["additionalContext"].startswith(f"Greenfield: `{skill}` is running."))
        self.assertIn("example.internal", hso["additionalContext"])
        self.assertIn("subagents", hso["additionalContext"])

    def test_listed_skill_with_no_config(self):
        self.assertNotice(self.run_hook(self.skill("superpowers:brainstorming")),
                          "PostToolUse", "superpowers:brainstorming")

    def test_unlisted_skill(self):
        self.assertIsNone(self.run_hook(self.skill("simplify")))

    def test_prefix_is_not_a_match(self):
        self.assertIsNone(self.run_hook(self.skill("superpowers:brainstorming-extra")))

    def test_other_tool(self):
        payload = self.skill("superpowers:brainstorming")
        payload["tool_name"] = "Write"
        self.assertIsNone(self.run_hook(payload))

    def test_slash_command(self):
        self.assertNotice(self.run_hook(self.prompt("/superpowers:writing-plans")),
                          "UserPromptSubmit", "superpowers:writing-plans")

    def test_slash_command_with_arguments_and_leading_space(self):
        self.assertNotice(self.run_hook(self.prompt("  /superpowers:brainstorming a CLI for notes")),
                          "UserPromptSubmit", "superpowers:brainstorming")

    def test_ordinary_prompt(self):
        self.assertIsNone(self.run_hook(self.prompt("let's use superpowers:brainstorming later")))

    def test_configured_list(self):
        self.config({"greenfield_skills": ["mine:design"]})
        self.assertNotice(self.run_hook(self.skill("mine:design")), "PostToolUse", "mine:design")
        self.assertIsNone(self.run_hook(self.skill("superpowers:brainstorming")))

    def test_empty_list_disables(self):
        self.config({"greenfield_skills": []})
        self.assertIsNone(self.run_hook(self.skill("superpowers:brainstorming")))

    def test_malformed_config_uses_default(self):
        self.config("{not json")
        self.assertNotice(self.run_hook(self.skill("superpowers:brainstorming")),
                          "PostToolUse", "superpowers:brainstorming")

    def test_malformed_input(self):
        self.assertIsNone(self.run_hook("not json"))
        self.assertIsNone(self.run_hook([1, 2]))
        self.assertIsNone(self.run_hook({"hook_event_name": "PostToolUse", "tool_name": "Skill",
                                         "tool_input": {"skill": 7}}))
        self.assertIsNone(self.run_hook({"hook_event_name": "UserPromptSubmit", "prompt": None}))
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `python3 -m unittest tests.test_greenfield -v`
Expected: the `GreenfieldHookTest` tests FAIL (the script doesn't exist: non-zero exit with "can't open file"); the six `GreenfieldSkillsTest` tests still pass.

- [ ] **Step 3: Implement**

Create `install/hooks/okf-greenfield.py`:

```python
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
        name = (data.get("tool_input") or {}).get("skill")
        return name if isinstance(name, str) and name in skills else None
    if event == "UserPromptSubmit" and isinstance(data.get("prompt"), str):
        m = re.match(r"\s*/(\S+)", data["prompt"])
        return m.group(1) if m and m.group(1) in skills else None
    return None


def main():
    data = json.load(sys.stdin)
    if not isinstance(data, dict):
        return
    _, config = okf_catalogs.load()
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
```

Then make it executable:

```bash
chmod +x install/hooks/okf-greenfield.py
```

- [ ] **Step 4: Run the tests to make sure they pass**

Run: `python3 -m unittest tests.test_greenfield -v`
Expected: PASS (17 tests)

- [ ] **Step 5: Commit**

```bash
git add install/hooks/okf-greenfield.py tests/test_greenfield.py
git commit -m "okf-greenfield hook: greenfield notice when a listed skill starts

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Register the hook in `setup.py`

`HOOKS` maps each event to one script, and PostToolUse is already taken by `okf-memory-mirror.py`. Make it a list of `(event, matcher, script)` entries.

**Files:**
- Modify: `install/setup.py` (`HOOKS`, `merge_settings`, the `install` line of the module docstring if needed)
- Test: `tests/test_setup_hooks.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_setup_hooks.py`:

```python
import contextlib
import importlib.util
import io
import json
import os
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETUP = os.path.join(REPO, "install", "setup.py")


class MergeSettingsTest(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.old_home = os.environ.get("HOME")
        os.environ["HOME"] = self.home.name
        os.makedirs(os.path.join(self.home.name, ".claude"))
        spec = importlib.util.spec_from_file_location("okf_setup", SETUP)
        self.setup_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.setup_mod)  # constants pick up the temporary HOME
        self.settings_path = os.path.join(self.home.name, ".claude", "settings.json")
        self.unrelated = {"matcher": "Skill", "hooks": [{"type": "command", "command": "log-skill.sh"}]}
        with open(self.settings_path, "w") as f:
            json.dump({"hooks": {"PostToolUse": [self.unrelated]}, "theme": "dark"}, f)

    def tearDown(self):
        os.environ["HOME"] = self.old_home
        self.home.cleanup()

    def merge(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.setup_mod.merge_settings({"memory_tools": ["mcp__memory__save_memory"]})
        with open(self.settings_path) as f:
            return json.load(f), out.getvalue()

    @staticmethod
    def groups_for(settings, event, script):
        command = f"~/.claude/hooks/{script}"
        return [g for g in settings["hooks"].get(event, [])
                if any(h.get("command") == command for h in g["hooks"])]

    def test_registers_every_hook(self):
        settings, _ = self.merge()
        self.assertEqual(settings["theme"], "dark")
        self.assertIn(self.unrelated, settings["hooks"]["PostToolUse"])
        self.assertEqual(len(self.groups_for(settings, "SessionStart", "okf-session.py")), 1)
        self.assertEqual(len(self.groups_for(settings, "Stop", "okf-reminder.py")), 1)
        mirror = self.groups_for(settings, "PostToolUse", "okf-memory-mirror.py")
        self.assertEqual([g["matcher"] for g in mirror], ["Write|Edit|mcp__memory__save_memory"])
        green = self.groups_for(settings, "PostToolUse", "okf-greenfield.py")
        self.assertEqual([g["matcher"] for g in green], ["Skill"])
        prompt = self.groups_for(settings, "UserPromptSubmit", "okf-greenfield.py")
        self.assertEqual(len(prompt), 1)
        self.assertNotIn("matcher", prompt[0])

    def test_second_run_changes_nothing(self):
        first, _ = self.merge()
        second, out = self.merge()
        self.assertEqual(first, second)
        self.assertEqual(out, "")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `python3 -m unittest tests.test_setup_hooks -v`
Expected: `test_registers_every_hook` FAILS (no `okf-greenfield.py` groups); `test_second_run_changes_nothing` passes.

- [ ] **Step 3: Implement**

In `install/setup.py`, replace the `HOOKS` dict:

```python
HOOKS = {
    "SessionStart": (None, "okf-session.py"),
    "PostToolUse": ("Write|Edit", "okf-memory-mirror.py"),
    "Stop": (None, "okf-reminder.py"),
}
```

with:

```python
HOOKS = [  # (event, matcher, script); a script may serve several events
    ("SessionStart", None, "okf-session.py"),
    ("PostToolUse", "Write|Edit", "okf-memory-mirror.py"),
    ("PostToolUse", "Skill", "okf-greenfield.py"),
    ("UserPromptSubmit", None, "okf-greenfield.py"),
    ("Stop", None, "okf-reminder.py"),
]
```

In `merge_settings`, replace:

```python
    for event, (matcher, script) in HOOKS.items():
        if event == "PostToolUse":
            matcher = "|".join(["Write", "Edit"] + (config.get("memory_tools") or []))
```

with:

```python
    for event, matcher, script in HOOKS:
        if script == "okf-memory-mirror.py":
            matcher = "|".join(["Write", "Edit"] + (config.get("memory_tools") or []))
```

`install_hooks` copies every `.py` in `install/hooks/`, so it needs no change.

- [ ] **Step 4: Run all tests**

Run: `python3 -m unittest discover -s tests -v`
Expected: PASS (all tests in the three files)

- [ ] **Step 5: Commit**

```bash
git add install/setup.py tests/test_setup_hooks.py
git commit -m "setup.py: register several hooks per event; add okf-greenfield

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Instructions and docs

**Files:**
- Modify: `install/CLAUDE-block.md:20-21`
- Modify: `AGENTS.md` (hook list)
- Modify: `README.md:23` and the `--memory-tool` paragraph

- [ ] **Step 1: CLAUDE.md block**

In `install/CLAUDE-block.md`, replace:

```markdown
- Before working on something within the catalog's scope, check it for an
  existing concept and use it as context.
```

with:

```markdown
- Before working on something within the catalog's scope, check it for an
  existing concept and use it as context, unless a greenfield notice is
  active for the current work; then use the catalog only when I ask.
```

- [ ] **Step 2: AGENTS.md hook list**

In `AGENTS.md`, replace `into a private memory store only in addition. Three hooks in` with `into a private memory store only in addition. Four hooks in`, and after the `okf-reminder.py` bullet:

```markdown
  - `okf-reminder.py` (Stop) reminds it at the end of turns that touched
    real systems without touching the catalog.
```

add:

```markdown
  - `okf-greenfield.py` (PostToolUse on `Skill`, and UserPromptSubmit for
    typed slash commands) gives design and planning work a clean start.
    When a skill listed in `greenfield_skills` in
    `~/.claude/okf-catalogs.json` runs (by default the superpowers
    brainstorming, planning and plan-execution skills), it tells the
    session not to consult the catalog or memory stores unless asked, and
    to keep the owner's private details out of what it writes, since
    designs and plans often end up in public repositories.
```

- [ ] **Step 3: README.md**

Replace `` `install` adds three hooks and a block in `~/.claude/CLAUDE.md`. `` with `` `install` adds four hooks and a block in `~/.claude/CLAUDE.md`. ``

After the paragraph ending `into the catalog too.`, add:

```markdown
While a design or planning skill runs, the `okf-greenfield.py` hook tells
Claude to work without the catalog unless you ask, and to keep your private
details out of specs, plans and code. Choose the skills with
`"greenfield_skills": [...]` in `~/.claude/okf-catalogs.json`; an empty
list turns it off.
```

- [ ] **Step 4: Lint and tests**

Run: `python3 tools/okf.py lint; echo exit=$?`
Expected: `exit=0`

Run: `python3 -m unittest discover -s tests -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add install/CLAUDE-block.md AGENTS.md README.md
git commit -m "Document the greenfield hook; CLAUDE.md block defers to it

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Live check and the two open questions

This answers the spec's two "to confirm" points without changing `~/.claude`: it loads the hooks for one run with `--settings`.

**Files:**
- Create (scratch, not committed): `$SCRATCH/greenfield-settings.json`, where `$SCRATCH` is a temporary directory such as the session scratchpad

- [ ] **Step 1: Write the one-off settings file**

Run from the repository root (the hook paths use `$PWD`):

```bash
SCRATCH=$(mktemp -d)
cat > "$SCRATCH/greenfield-settings.json" <<EOF
{
  "hooks": {
    "PostToolUse": [{"matcher": "Skill", "hooks": [{"type": "command",
      "command": "python3 $PWD/install/hooks/okf-greenfield.py", "timeout": 10}]}],
    "UserPromptSubmit": [{"hooks": [{"type": "command",
      "command": "python3 $PWD/install/hooks/okf-greenfield.py", "timeout": 10}]}]
  }
}
EOF
```

- [ ] **Step 2: Does PostToolUse context reach the model on a Skill call?**

Run, from a scratch directory outside any repository:

```bash
cd "$SCRATCH" && claude -p --settings "$SCRATCH/greenfield-settings.json" \
  "Call the Skill tool with skill superpowers:brainstorming. Do not follow its instructions. \
Reply with exactly SEEN if, after the skill loaded, you received context beginning 'Greenfield:', otherwise NONE."
```

Expected: `SEEN`. If it says `NONE`, change the PostToolUse entry to PreToolUse (same matcher) in `setup.py`'s `HOOKS` and in the test, let `invoked_skill` accept `PreToolUse` too, re-run Tasks 3 and 4's tests, and repeat this step.

- [ ] **Step 3: Does a typed slash command go through the Skill tool?**

Run with only the PostToolUse hook (delete the `UserPromptSubmit` block from the settings file first):

```bash
cd "$SCRATCH" && claude -p --settings "$SCRATCH/greenfield-settings.json" \
  "/superpowers:brainstorming Reply with exactly SEEN if you have received context beginning 'Greenfield:', otherwise NONE. Do not follow the skill's instructions."
```

- `SEEN`: typed commands reach the Skill tool. Remove the `("UserPromptSubmit", None, "okf-greenfield.py")` entry from `HOOKS`, the UserPromptSubmit assertions from `test_registers_every_hook`, the UserPromptSubmit branch from `invoked_skill` and its tests, and the "and UserPromptSubmit" wording from the hook docstring, `AGENTS.md` and the spec.
- `NONE`: keep UserPromptSubmit. Restore its block and re-run to confirm `SEEN`.

- [ ] **Step 4: Run everything**

Run: `python3 -m unittest discover -s tests -v && python3 tools/okf.py lint`
Expected: PASS and lint exit 0.

- [ ] **Step 5: Record the outcome in the spec and commit**

Under "To confirm during implementation" in `docs/superpowers/specs/2026-10-27-greenfield-notice-design.md`, add one line per question saying what the check showed (for example "Confirmed 2026-10-27: PostToolUse context reaches the model; typed slash commands don't use the Skill tool, so UserPromptSubmit stays."). Then:

```bash
git add -A install tests docs AGENTS.md README.md
git commit -m "Greenfield hook: record live-check results

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Installing the hook on a real machine (`setup.py install`) is left to the owner.
