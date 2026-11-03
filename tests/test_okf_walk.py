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
