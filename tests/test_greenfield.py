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
        self.assertIsNone(self.run_hook({"hook_event_name": "PostToolUse", "tool_name": "Skill",
                                         "tool_input": "superpowers:brainstorming"}))

    def test_wrong_shape_config_uses_default_list(self):
        for bad in ([], "null", {"catalogs": ["x"]}):
            with self.subTest(config=bad):
                self.config(bad)
                self.assertNotice(self.run_hook(self.skill("superpowers:brainstorming")),
                                  "PostToolUse", "superpowers:brainstorming")

    def test_prompt_slash_command_on_later_line(self):
        self.assertNotice(self.run_hook(self.prompt("\n/superpowers:writing-plans\nwith details")),
                          "UserPromptSubmit", "superpowers:writing-plans")

    def test_prompt_path_is_not_a_skill(self):
        self.assertIsNone(self.run_hook(self.prompt("/home/user/file")))


if __name__ == "__main__":
    unittest.main()
