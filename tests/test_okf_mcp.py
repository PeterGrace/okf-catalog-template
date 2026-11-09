"""The okf-mcp workflow: okf.py's freeze guard and publish after mv, setup.py serve/install, hooks."""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OKF = os.path.join(REPO, "tools", "okf.py")
SETUP = os.path.join(REPO, "install", "setup.py")
SESSION_HOOK = os.path.join(REPO, "install", "hooks", "okf-session.py")
GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}


def git(cwd, *args):
    return subprocess.run(["git", "-C", cwd, *args], check=True, capture_output=True, text=True,
                          env={**os.environ, **GIT_ENV}).stdout


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


def okf(root, *args, env=None):
    return subprocess.run([sys.executable, os.path.join(root, "tools", "okf.py"), *args],
                          capture_output=True, text=True,
                          env={**os.environ, **GIT_ENV, **(env or {})})


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class CatalogRepo(unittest.TestCase):
    """A one-concept catalog cloned from a bare remote, with this tools/okf.py."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        remote = os.path.join(self.tmp.name, "remote.git")
        self.root = os.path.join(self.tmp.name, "catalog")
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", remote], check=True)
        subprocess.run(["git", "clone", "-q", remote, self.root], check=True, capture_output=True)
        git(self.root, "checkout", "-q", "-b", "main")
        os.makedirs(os.path.join(self.root, "tools"))
        shutil.copy(OKF, os.path.join(self.root, "tools", "okf.py"))
        write(os.path.join(self.root, "index.md"), "# Catalog\n\n* [A](a.md) - A thing.\n")
        write(os.path.join(self.root, "log.md"), "# Log\n")
        write(os.path.join(self.root, "a.md"),
              "---\ntype: Note\ntitle: A\ndescription: A thing.\n---\n\nBody.\n")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", "init")
        git(self.root, "push", "-q", "origin", "main")

    def tearDown(self):
        self.tmp.cleanup()


class PublishAfterMoveTest(CatalogRepo):
    def assertPublishedRename(self, *publish_args):
        r = okf(self.root, "mv", "a.md", "b.md")
        self.assertEqual(r.returncode, 0, r.stderr)
        r = okf(self.root, "publish", "-m", "rename", *publish_args)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(git(self.root, "status", "--porcelain"), "")
        files = git(self.root, "ls-tree", "-r", "--name-only", "origin/main").split()
        self.assertIn("b.md", files)
        self.assertNotIn("a.md", files)

    def test_publish_named_old_and_new_paths(self):
        self.assertPublishedRename("a.md", "b.md", "index.md")

    def test_publish_all(self):
        self.assertPublishedRename("--all")

    def test_unstaged_deletion_is_still_published(self):
        os.remove(os.path.join(self.root, "a.md"))
        write(os.path.join(self.root, "index.md"), "# Catalog\n")
        r = okf(self.root, "publish", "-m", "drop", "a.md", "index.md")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("a.md", git(self.root, "ls-tree", "-r", "--name-only", "origin/main").split())


class FreezeGuardTest(CatalogRepo):
    def setUp(self):
        super().setUp()
        write(os.path.join(self.root, ".okf-catalog.json"),
              json.dumps({"name": "n", "owner": "o", "scope": "s",
                          "mcp": {"server": "kb", "catalog": "acme"}}))

    def test_refuses_commands_naming_the_server(self):
        for args in (["lint"], ["log", "x"], ["session", "start", "--id", "s1"]):
            r = okf(self.root, *args)
            self.assertEqual(r.returncode, 1, args)
            self.assertIn("frozen snapshot", r.stderr)
            self.assertIn("'acme'", r.stderr)
            self.assertIn("mcp__kb__*", r.stderr)
        with open(os.path.join(self.root, "log.md")) as f:
            self.assertEqual(f.read(), "# Log\n")

    def test_allows_session_cleanup(self):
        r = okf(self.root, "session", "list")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_maintenance_override(self):
        r = okf(self.root, "lint", env={"OKF_GIT_MAINTENANCE": "1"})
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_git_only_catalog_is_not_frozen(self):
        write(os.path.join(self.root, ".okf-catalog.json"), json.dumps({"name": "n"}))
        self.assertEqual(okf(self.root, "lint").returncode, 0)


class SetupTest(unittest.TestCase):
    """setup.py from a copy of the template, with HOME pointing at a scratch directory."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_home = os.environ.get("HOME")
        self.home = os.path.join(self.tmp.name, "home")
        os.makedirs(os.path.join(self.home, ".claude"))
        os.environ["HOME"] = self.home
        self.repo = os.path.realpath(os.path.join(self.tmp.name, "catalog"))
        for rel in ("install", "tools", ".claude", "AGENTS.md"):
            src = os.path.join(REPO, rel)
            (shutil.copytree if os.path.isdir(src) else shutil.copy)(src, os.path.join(self.repo, rel))
        self.setup = load(os.path.join(self.repo, "install", "setup.py"), "okf_setup_mcp")
        self.quiet(self.setup.cmd_init, owner="jdoe", scope="my work at Acme", name="Acme")

    def tearDown(self):
        if self.old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self.old_home
        self.tmp.cleanup()

    def quiet(self, fn, **kw):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            fn(type("Args", (), kw)())
        return out.getvalue()

    def serve(self, server="okf-mcp"):
        return self.quiet(self.setup.cmd_serve, catalog="acme", server=server)

    def install(self):
        return self.quiet(self.setup.cmd_install, projects=None, default=False, memory_tool=None)

    def read(self, *rel):
        with open(os.path.join(*rel)) as f:
            return f.read()

    def test_serve_records_server_and_switches_agents_md(self):
        self.serve(server="kb")
        identity = json.loads(self.read(self.repo, ".okf-catalog.json"))
        self.assertEqual(identity["mcp"], {"server": "kb", "catalog": "acme"})
        agents = self.read(self.repo, "AGENTS.md")
        self.assertIn("catalog **`acme` on the\nkb MCP server**", agents)
        self.assertIn("my work at Acme", agents)
        self.assertNotIn("{{", agents)
        self.assertNotIn("session start", agents)
        self.assertFalse(any(n.startswith("okf-")
                             for n in os.listdir(os.path.join(self.repo, ".claude", "skills"))))

    def test_serve_fills_a_template_okf_py(self):
        shutil.copy(OKF, os.path.join(self.repo, "tools", "okf.py"))
        self.serve()
        self.assertNotIn("{{", self.read(self.repo, "tools", "okf.py"))

    def test_serve_rejects_bad_names(self):
        with self.assertRaises(SystemExit):
            self.quiet(self.setup.cmd_serve, catalog="a b", server="okf-mcp")

    def test_git_catalog_install_keeps_git_workflow_only(self):
        self.install()
        md = self.read(self.home, ".claude", "CLAUDE.md")
        self.assertIn("## A catalog in a git checkout", md)
        self.assertNotIn("okf-mcp server\n", md)
        self.assertNotIn("okf-catalog:if", md)
        self.assertFalse(os.path.exists(os.path.join(self.home, ".claude", "skills")))
        entry = json.loads(self.read(self.home, ".claude", "okf-catalogs.json"))["catalogs"][0]
        self.assertNotIn("mcp", entry)

    def test_served_install_registers_mcp_and_installs_skills(self):
        self.serve(server="kb")
        self.install()
        entry = json.loads(self.read(self.home, ".claude", "okf-catalogs.json"))["catalogs"][0]
        self.assertEqual(entry["mcp"], {"server": "kb", "catalog": "acme"})
        md = self.read(self.home, ".claude", "CLAUDE.md")
        self.assertIn("## A catalog on an okf-mcp server", md)
        self.assertNotIn("## A catalog in a git checkout", md)
        self.assertIn("## Every catalog", md)
        skill = self.read(self.home, ".claude", "skills", "okf-link-check", "SKILL.md")
        self.assertIn("mcp__kb__", skill)
        self.assertNotIn("mcp__okf-mcp__", skill)
        self.assertEqual(sorted(os.listdir(os.path.join(self.home, ".claude", "skills"))),
                         sorted(os.listdir(os.path.join(self.repo, "install", "skills"))))
        self.assertEqual(self.install().count("installed"), 0)  # a second run changes nothing

    def test_serving_after_a_git_install_replaces_the_block(self):
        self.install()
        self.serve()
        self.install()
        md = self.read(self.home, ".claude", "CLAUDE.md")
        self.assertEqual(md.count("<!-- okf-catalog:begin"), 1)
        self.assertNotIn("## A catalog in a git checkout", md)

    def test_install_leaves_symlinked_skills(self):
        self.serve()
        target = os.path.join(self.tmp.name, "elsewhere")
        os.makedirs(target)
        os.makedirs(os.path.join(self.home, ".claude", "skills"))
        link = os.path.join(self.home, ".claude", "skills", "okf-link-check")
        os.symlink(target, link)
        self.assertIn("is a symlink", self.install())
        self.assertEqual(os.listdir(target), [])

    def test_mixed_machine_gets_both_workflows(self):
        block = self.setup.claude_block({"catalogs": [{"path": "/a", "mcp": {"catalog": "x"}},
                                                      {"path": "/b"}]})
        self.assertIn("## A catalog on an okf-mcp server", block)
        self.assertIn("## A catalog in a git checkout", block)
        self.assertNotIn("okf-catalog:if", block)


class SessionHookTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = self.tmp.name
        os.makedirs(os.path.join(self.home, ".claude"))

    def tearDown(self):
        self.tmp.cleanup()

    def context(self, catalogs):
        with open(os.path.join(self.home, ".claude", "okf-catalogs.json"), "w") as f:
            json.dump({"catalogs": catalogs}, f)
        proc = subprocess.run([sys.executable, SESSION_HOOK], capture_output=True, text=True,
                              input=json.dumps({"session_id": "s1", "cwd": self.home}),
                              env={**os.environ, "HOME": self.home})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]

    def test_served_catalog_without_a_checkout_is_named_by_server(self):
        text = self.context([{"path": "~/missing", "name": "Acme", "default": True,
                              "mcp": {"server": "kb", "catalog": "acme"}}])
        self.assertIn("catalog `acme` on the kb MCP server", text)
        self.assertIn("`mcp__kb__*`", text)
        self.assertNotIn("session start", text)

    def test_git_catalog_gets_its_worktree_command(self):
        os.makedirs(os.path.join(self.home, "cat"))
        text = self.context([{"path": os.path.join(self.home, "cat"), "default": True}])
        self.assertIn("session start --id s1", text)

    def test_touches_counts_calls_to_the_catalog_server(self):
        catalogs = load(os.path.join(REPO, "install", "hooks", "okf_catalogs.py"), "okf_catalogs_t")
        cat = {"path": "/nowhere", "raw_path": "/nowhere", "mcp": {"server": "kb", "catalog": "acme"}}
        self.assertTrue(catalogs.touches(cat, {"name": "mcp__kb__search", "input": {}}))
        self.assertFalse(catalogs.touches(cat, {"name": "mcp__other__search", "input": {}}))


if __name__ == "__main__":
    unittest.main()
