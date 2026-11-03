import importlib.util
import os
import shutil
import subprocess
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETUP = os.path.join(REPO, "install", "setup.py")


def load_setup(path):
    spec = importlib.util.spec_from_file_location("okf_setup_copy", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def git(cwd, *args):
    subprocess.run(["git", "-C", cwd, *args], check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"})


class CatalogPathTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.main = os.path.realpath(os.path.join(self.tmp.name, "catalog"))
        os.makedirs(os.path.join(self.main, "install"))
        shutil.copy(SETUP, os.path.join(self.main, "install", "setup.py"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_outside_git_is_the_checkout_itself(self):
        mod = load_setup(os.path.join(self.main, "install", "setup.py"))
        self.assertEqual(mod.catalog_path(), self.main)

    def test_main_checkout(self):
        git(self.main, "init", "-q")
        mod = load_setup(os.path.join(self.main, "install", "setup.py"))
        self.assertEqual(mod.catalog_path(), self.main)

    def test_worktree_resolves_to_main_checkout(self):
        git(self.main, "init", "-q")
        git(self.main, "add", "-A")
        git(self.main, "commit", "-qm", "x")
        wt = os.path.join(self.main, ".worktrees", "s1")
        git(self.main, "worktree", "add", "-q", wt)
        mod = load_setup(os.path.join(wt, "install", "setup.py"))
        self.assertEqual(mod.REPO, os.path.realpath(wt))
        self.assertEqual(mod.catalog_path(), self.main)


if __name__ == "__main__":
    unittest.main()
