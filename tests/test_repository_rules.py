"""Document contract checks; no production or synthetic business data."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class RepositoryRulesTests(unittest.TestCase):
    def test_contribution_entry_point_and_relative_links(self):
        readme = (ROOT / "README.md").read_text()
        self.assertIn("## Start contributing", readme)
        for name in ("README.md", "INDEX.md"):
            content = (ROOT / name).read_text()
            links = re.findall(r"\[[^\]]+\]\(([^)]+)\)", content)
            self.assertTrue(links, name)
            for target in links:
                with self.subTest(source=name, target=target):
                    self.assertTrue((ROOT / target).is_file())

    def test_scope_ownership_and_evidence_are_documented(self):
        rules = (ROOT / "AGENTS.md").read_text()
        readme = (ROOT / "README.md").read_text()
        for requirement in ("No refactors outside scope", "Commit only after validation",
                            "append-only", "only the reviewer sets Accepted"):
            self.assertIn(requirement, rules)
        self.assertIn("reviewer owns acceptance", rules)
        self.assertIn("reviewed SHA", readme)

    def test_task_is_indexed_once_with_one_status(self):
        index = (ROOT / "INDEX.md").read_text()
        status = (ROOT / "log/STATUS.md").read_text()
        for content in (index, status):
            rows = [line for line in content.splitlines() if line.startswith("| P0001 |")]
            self.assertEqual(len(rows), 1)
        self.assertTrue((ROOT / "tasks/P0001.md").is_file())
        self.assertRegex(status, r"\| P0001 \| (In progress|Awaiting review) \|")


if __name__ == "__main__":
    unittest.main()
