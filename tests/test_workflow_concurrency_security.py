"""PR-controlled branch labels must not cancel trusted branch verification."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class WorkflowConcurrencySecurity(unittest.TestCase):
    def test_groups_use_full_event_ref_not_untrusted_branch_label(self):
        for name in ['verify-v2', 'repository-hygiene', 'restore-regression']:
            with self.subTest(workflow=name):
                text = (ROOT / '.github/workflows' / (name + '.yml')).read_text()
                group = re.search(r'^  group: (.+)$', text, re.M).group(1)
                self.assertEqual(group, name + '-${{ github.ref }}')
                # A fork can choose head_ref=main, or match another fork's
                # label, but cannot choose GitHub's numbered pull-request ref.
                contexts = ['refs/heads/main', 'refs/pull/56/merge', 'refs/pull/57/merge']
                keys = [group.replace('${{ github.ref }}', ref) for ref in contexts]
                self.assertEqual(len(set(keys)), len(contexts))
                self.assertIn('cancel-in-progress: true', text)


if __name__ == '__main__':
    unittest.main()
