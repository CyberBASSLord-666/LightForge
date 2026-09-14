"""Exercise the publisher's source boundary without loading release dependencies."""
import ast
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'tools/publish_github_release.py').read_text(encoding='utf-8')
TREE = ast.parse(SOURCE)
FUNCTIONS = {'run', 'require', 'require_candidate_worktree'}
BOUNDARY = ast.Module(body=[
    node for node in TREE.body
    if (isinstance(node, ast.FunctionDef) and node.name in FUNCTIONS)
    or (isinstance(node, ast.Assign) and any(
        isinstance(target, ast.Name) and target.id == 'RELEASE_ENFORCEMENT_PATHS'
        for target in node.targets
    ))
], type_ignores=[])
NAMESPACE = {'subprocess': subprocess, 're': re}
exec(compile(BOUNDARY, '<publisher-source-boundary>', 'exec'), NAMESPACE)


class PublisherCandidateWorktreeTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.previous = Path.cwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, self.previous)
        self.git('init', '-q')
        for relative in (
            'version.json', 'web/version.js', 'android/AndroidManifest.xml',
            'tools/publish_github_release.py', 'tools/release_material_handoff.py',
            '.github/workflows/publish-release.yml', 'RELEASE_NOTES.md',
        ):
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text('candidate\n', encoding='utf-8')
        self.git('add', '.')
        self.git('-c', 'user.name=Release Boundary Test', '-c',
                 'user.email=release-boundary-test@example.invalid',
                 'commit', '-qm', 'candidate')
        self.commit = self.git('rev-parse', 'HEAD')

    def git(self, *args):
        return subprocess.check_output(('git', *args), text=True,
                                       stderr=subprocess.DEVNULL).strip()

    def verify(self):
        NAMESPACE['require_candidate_worktree'](self.commit)

    def test_clean_candidate_and_inert_release_notes_are_allowed(self):
        self.verify()
        (self.root / 'RELEASE_NOTES.md').write_text('new notes\n', encoding='utf-8')
        self.verify()

    def test_unstaged_publisher_changes_fail_even_though_head_is_candidate(self):
        (self.root / 'tools/publish_github_release.py').write_text('changed\n', encoding='utf-8')
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.commit)
        with self.assertRaises(subprocess.CalledProcessError):
            self.verify()

    def test_staged_handoff_changes_fail_even_though_head_is_candidate(self):
        (self.root / 'tools/release_material_handoff.py').write_text('changed\n', encoding='utf-8')
        self.git('add', 'tools/release_material_handoff.py')
        with self.assertRaises(subprocess.CalledProcessError):
            self.verify()

    def test_runtime_asset_and_workflow_changes_fail(self):
        for relative in ('web/version.js', 'android/AndroidManifest.xml',
                         'version.json', '.github/workflows/publish-release.yml'):
            with self.subTest(path=relative):
                target = self.root / relative
                target.write_text('changed\n', encoding='utf-8')
                with self.assertRaises(subprocess.CalledProcessError):
                    self.verify()
                target.write_text('candidate\n', encoding='utf-8')

    def test_post_candidate_head_is_rejected(self):
        (self.root / 'RELEASE_NOTES.md').write_text('new notes\n', encoding='utf-8')
        self.git('add', 'RELEASE_NOTES.md')
        self.git('-c', 'user.name=Release Boundary Test', '-c',
                 'user.email=release-boundary-test@example.invalid',
                 'commit', '-qm', 'post candidate request')
        with self.assertRaisesRegex(ValueError, 'exact verified candidate'):
            self.verify()

    def test_invalid_commit_is_rejected_before_git(self):
        for value in (None, 123, 'HEAD', '-invalid', 'a' * 39):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, 'Invalid source commit'):
                    NAMESPACE['require_candidate_worktree'](value)

    def test_main_checks_worktree_before_attestation_and_api(self):
        main = next(node for node in TREE.body
                    if isinstance(node, ast.FunctionDef) and node.name == 'main')
        calls = {}
        for node in ast.walk(main):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                calls.setdefault(node.func.id, []).append(node.lineno)
        boundary = min(calls['require_candidate_worktree'])
        self.assertLess(boundary, min(calls['load_physical_validation_attestation']))
        self.assertLess(boundary, min(calls['api']))
        self.assertLess(boundary, min(calls['create_draft']))
        self.assertIn('tools/release_material_handoff.py', NAMESPACE['RELEASE_ENFORCEMENT_PATHS'])


if __name__ == '__main__':
    unittest.main()
