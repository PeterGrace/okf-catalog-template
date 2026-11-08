import json
import os
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "install", "hooks", "okf-reminder.py")


class ReminderHookTest(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        h = self.home.name
        os.makedirs(os.path.join(h, ".claude"))
        self.catalog = os.path.join(h, "catalog")
        self.project = os.path.join(h, "project")
        os.makedirs(self.catalog)
        os.makedirs(self.project)
        with open(os.path.join(h, ".claude", "okf-catalogs.json"), "w") as f:
            json.dump({"catalogs": [{"path": self.catalog, "default": True, "scope": "the test world"}]}, f)
        self.state = os.path.join(h, "state")
        self.transcript = os.path.join(h, "t.jsonl")
        self.turns = 0
        self.env = {**os.environ, "HOME": h, "OKF_REMINDER_STATE_DIR": self.state}
        for key in ("OKF_REMINDER_TURNS", "OKF_REMINDER_MINUTES", "OKF_REMINDER_CONTEXT"):
            self.env.pop(key, None)

    def tearDown(self):
        self.home.cleanup()

    def turn(self, command="ls", context=10_000, catalog=False):
        """Append one turn to the transcript: a prompt, one Bash call and a usage record."""
        self.turns += 1
        cmd = f"cat {self.catalog}/x.md" if catalog else command
        entries = [
            {"type": "user", "uuid": f"u{self.turns}", "message": {"content": f"prompt {self.turns}"}},
            {"type": "assistant", "message": {
                "content": [{"type": "tool_use", "id": f"t{self.turns}", "name": "Bash", "input": {"command": cmd}}],
                "usage": {"input_tokens": 2, "cache_read_input_tokens": context - 2, "cache_creation_input_tokens": 0}}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": f"t{self.turns}"}]}},
        ]
        with open(self.transcript, "a") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")

    def stop(self, **extra):
        payload = {"hook_event_name": "Stop", "session_id": "s1", "cwd": self.project,
                   "transcript_path": self.transcript, **extra}
        return self.run_hook(payload)

    def run_hook(self, payload, env=None):
        proc = subprocess.run([sys.executable, SCRIPT], input=json.dumps(payload), capture_output=True,
                              text=True, env={**self.env, **(env or {})})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stderr, "")
        return json.loads(proc.stdout) if proc.stdout.strip() else None

    def assertReminds(self, out, why):
        self.assertIsNotNone(out)
        self.assertEqual(out["decision"], "block")
        self.assertIn(why, out["reason"])
        self.assertIn("the test world", out["reason"])

    def test_coding_turns_are_silent(self):
        for _ in range(5):
            self.turn("cargo test")
            self.assertIsNone(self.stop())

    def test_reminds_on_third_system_turn(self):
        self.turn("kubectl get pods")
        self.assertIsNone(self.stop())
        self.turn("cargo build")  # doesn't count
        self.assertIsNone(self.stop())
        self.turn("ssh host uptime")
        self.assertIsNone(self.stop())
        self.turn("kubectl logs x")
        self.assertReminds(self.stop(), "3 turns touched real systems")
        self.turn("kubectl logs y")  # the count started over
        self.assertIsNone(self.stop())

    def test_turn_count_setting(self):
        self.turn("kubectl get pods")
        self.assertReminds(self.run_hook({"hook_event_name": "Stop", "session_id": "s1", "cwd": self.project,
                                          "transcript_path": self.transcript}, {"OKF_REMINDER_TURNS": "1"}),
                           "1 turns")

    def test_catalog_touch_clears_count(self):
        self.turn("kubectl get pods")
        self.stop()
        self.turn("kubectl get svc")
        self.stop()
        self.turn(catalog=True)
        self.assertIsNone(self.stop())
        self.turn("kubectl get nodes")
        self.assertIsNone(self.stop())

    def test_same_turn_is_counted_once(self):
        self.turn("kubectl get pods")
        for _ in range(4):
            self.assertIsNone(self.stop())

    def test_reentry_after_reminder_is_silent(self):
        self.turn("kubectl get pods")
        self.assertIsNone(self.run_hook({"hook_event_name": "Stop", "session_id": "s1", "cwd": self.project,
                                         "transcript_path": self.transcript, "stop_hook_active": True},
                                        {"OKF_REMINDER_TURNS": "1"}))

    def test_reminds_after_minutes(self):
        self.turn("kubectl get pods")
        self.assertIsNone(self.stop())
        path = os.path.join(self.state, "s1.json")
        with open(path) as f:
            state = json.load(f)
        state["since"] -= 21 * 60
        with open(path, "w") as f:
            json.dump(state, f)
        self.turn("cargo build")
        self.assertReminds(self.stop(), "for 21 minutes")

    def test_reminds_on_large_context_once_per_step(self):
        self.turn("kubectl get pods", context=160_000)
        self.assertReminds(self.stop(), "160k tokens")
        self.turn("kubectl get svc", context=200_000)
        self.assertIsNone(self.stop())  # under the next step
        self.turn("kubectl get svc", context=265_000)
        self.assertReminds(self.stop(), "265k tokens")
        self.turn("kubectl get svc", context=40_000)  # compacted
        self.assertIsNone(self.stop())
        self.turn("kubectl get svc", context=155_000)
        self.assertReminds(self.stop(), "155k tokens")

    def test_large_context_without_system_turns_is_silent(self):
        self.turn("cargo test", context=400_000)
        self.assertIsNone(self.stop())

    def test_silent_inside_catalog_and_without_catalog(self):
        self.turn("kubectl get pods")
        payload = {"hook_event_name": "Stop", "session_id": "s1", "cwd": self.catalog,
                   "transcript_path": self.transcript}
        self.assertIsNone(self.run_hook(payload, {"OKF_REMINDER_TURNS": "1"}))
        os.remove(os.path.join(self.home.name, ".claude", "okf-catalogs.json"))
        self.assertIsNone(self.run_hook({**payload, "cwd": self.project}, {"OKF_REMINDER_TURNS": "1"}))

    def test_session_end_logs_unrecorded_turns(self):
        self.turn("kubectl get pods")
        self.stop()
        end = {"hook_event_name": "SessionEnd", "session_id": "s1", "cwd": self.project,
               "transcript_path": self.transcript, "reason": "prompt_input_exit"}
        self.assertIsNone(self.run_hook(end))
        with open(os.path.join(self.state, "unrecorded.jsonl")) as f:
            lines = [json.loads(line) for line in f]
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["session_id"], "s1")
        self.assertEqual(lines[0]["pending_turns"], 1)
        self.assertFalse(os.path.exists(os.path.join(self.state, "s1.json")))

    def test_session_end_with_nothing_pending(self):
        self.turn("cargo test")
        self.stop()
        self.run_hook({"hook_event_name": "SessionEnd", "session_id": "s1", "cwd": self.project})
        self.assertFalse(os.path.exists(os.path.join(self.state, "unrecorded.jsonl")))

    def test_bad_input_never_fails(self):
        proc = subprocess.run([sys.executable, SCRIPT], input="not json", capture_output=True, text=True,
                              env=self.env)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, "")


if __name__ == "__main__":
    unittest.main()
