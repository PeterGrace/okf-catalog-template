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
        if self.old_home is None:
            os.environ.pop("HOME", None)
        else:
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
        self.assertEqual(len(self.groups_for(settings, "SessionEnd", "okf-reminder.py")), 1)
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
