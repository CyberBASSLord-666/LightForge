"""The compatibility alias is explicit layout, never a runtime-validation waiver."""
from pathlib import Path
import importlib.util
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('consumer_layout', ROOT/'tools/prepare_consumer_toolchain_layout.py')
layout = importlib.util.module_from_spec(spec)
spec.loader.exec_module(layout)


class ConsumerLayoutTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.parent = Path(self.temp.name)
        self.root = self.parent/'checkout'
        self.root.mkdir()
        self.git('init', '-q')
        self.git('config', 'user.email', 'test@example.invalid')
        self.git('config', 'user.name', 'Fixture')
        (self.root/'source').write_text('original')
        self.git('add', '.')
        self.git('commit', '-qm', 'Fixture')
        self.alias = self.root/'toolchain'
        self.sibling = self.parent/'toolchain'
        self.env = {'GITHUB_ACTIONS': 'true', 'GITHUB_WORKSPACE': str(self.root)}

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], stderr=subprocess.STDOUT)

    def prepare(self):
        return layout.prepare(self.root, environment=self.env)

    def test_absent_target_is_only_layout_ready_and_idempotent(self):
        before = self.git('diff', 'HEAD')
        result = self.prepare()
        self.assertEqual(result['status'], 'layout-ready')
        self.assertEqual(result['installation'], 'pending-bootstrap')
        self.assertFalse(result['runtimeValidated'])
        self.assertEqual(os.readlink(self.alias), '../toolchain')
        self.assertFalse(self.prepare()['created'])
        self.assertEqual(before, self.git('diff', 'HEAD'))

    def test_existing_installation_is_not_claimed_validated(self):
        self.sibling.mkdir()
        (self.sibling/'jdk17').mkdir()
        result = self.prepare()
        self.assertFalse(result['runtimeValidated'])
        self.assertEqual(result['installation'], 'present-but-unvalidated')
        self.assertFalse((self.alias/'jdk17').is_symlink())
        self.assertTrue((self.alias/'jdk17').samefile(self.sibling/'jdk17'))

    def test_non_ci_preserves_custom_layout_and_overrides(self):
        self.alias.write_text('local setup')
        for flag in ('', 'false', 'True'):
            self.env.update(GITHUB_ACTIONS=flag, LIGHTFORGE_TOOLCHAIN_DIR='/custom')
            self.assertEqual(self.prepare()['status'], 'not-applicable')
        self.assertEqual(self.alias.read_text(), 'local setup')

    def test_missing_or_other_workspace_rejected_without_write(self):
        for value in ('', '.', str(self.parent)):
            self.env['GITHUB_WORKSPACE'] = value
            with self.assertRaises(RuntimeError): self.prepare()
            self.assertFalse(self.alias.is_symlink())

    def test_symlinked_workspace_rejected(self):
        other = self.parent/'other'
        other.symlink_to(self.root, target_is_directory=True)
        self.env['GITHUB_WORKSPACE'] = str(other)
        with self.assertRaises(RuntimeError): self.prepare()

    def test_symlinked_parent_rejected(self):
        other = self.parent/'parent-alias'
        other.symlink_to(self.parent, target_is_directory=True)
        root = other/'checkout'
        self.env['GITHUB_WORKSPACE'] = str(root)
        with self.assertRaises(RuntimeError): layout.prepare(root, environment=self.env)

    def test_nested_checkout_directory_rejected(self):
        nested = self.root/'nested'
        nested.mkdir()
        self.env['GITHUB_WORKSPACE'] = str(nested)
        with self.assertRaises(RuntimeError): layout.prepare(nested, environment=self.env)

    def test_project_overrides_rejected(self):
        for name in layout.PATH_OVERRIDES:
            self.env[name] = '/custom'
            with self.assertRaises(RuntimeError): self.prepare()
            del self.env[name]
        self.assertFalse(self.alias.is_symlink())

    def test_ignored_runner_discovery_environment_not_rewritten(self):
        self.env.update(JAVA_HOME='/runner/java', ANDROID_HOME='/runner/sdk',
                        ANDROID_SDK_ROOT='/runner/sdk', LD_LIBRARY_PATH='/runner/python')
        before = self.env.copy()
        self.prepare()
        self.assertEqual(self.env, before)

    def test_file_and_directory_collisions_preserved(self):
        self.alias.write_text('keep')
        with self.assertRaises(RuntimeError): self.prepare()
        self.assertEqual(self.alias.read_text(), 'keep')
        self.alias.unlink()
        self.alias.mkdir()
        with self.assertRaises(RuntimeError): self.prepare()
        self.assertTrue(self.alias.is_dir())

    def test_wrong_links_preserved_even_equivalent_absolute_target(self):
        for target in ('../missing', str(self.sibling), '../checkout/../toolchain'):
            self.alias.symlink_to(target)
            with self.assertRaises(RuntimeError): self.prepare()
            self.assertEqual(os.readlink(self.alias), target)
            self.alias.unlink()

    def test_symlink_or_file_sibling_rejected(self):
        self.sibling.symlink_to(self.parent/'missing')
        with self.assertRaises(RuntimeError): self.prepare()
        self.sibling.unlink()
        self.sibling.write_text('keep')
        with self.assertRaises(RuntimeError): self.prepare()
        self.assertFalse(self.alias.is_symlink())

    def test_tracked_leaf_rejected(self):
        self.alias.symlink_to('../toolchain')
        self.git('add', 'toolchain')
        with self.assertRaises(RuntimeError): self.prepare()

    def test_tracked_descendants_rejected_even_deleted_in_worktree(self):
        self.alias.mkdir()
        (self.alias/'source').write_text('tracked')
        self.git('add', '.')
        self.git('commit', '-qm', 'Tracked toolchain source')
        self.git('rm', '-rf', 'toolchain')
        with self.assertRaises(RuntimeError): self.prepare()
        self.assertFalse(self.alias.exists())

    def test_concurrent_correct_creator_is_idempotent(self):
        original = os.symlink
        def race(target, path, **kwargs):
            original(target, path, **kwargs)
            raise FileExistsError('concurrent creator')
        with patch.object(layout.os, 'symlink', side_effect=race):
            self.assertFalse(self.prepare()['created'])
        self.assertEqual(os.readlink(self.alias), '../toolchain')

    def test_concurrent_wrong_creator_is_not_overwritten(self):
        original = os.symlink
        def race(target, path, **kwargs):
            original('../wrong', path, **kwargs)
            raise FileExistsError('concurrent creator')
        with patch.object(layout.os, 'symlink', side_effect=race):
            with self.assertRaises(RuntimeError): self.prepare()
        self.assertEqual(os.readlink(self.alias), '../wrong')

    def test_sibling_redirect_during_creation_rejected(self):
        original = os.symlink
        def race(target, path, **kwargs):
            original(target, path, **kwargs)
            original('../outside', self.sibling)
        with patch.object(layout.os, 'symlink', side_effect=race):
            with self.assertRaises(RuntimeError): self.prepare()

    def test_checkout_swap_never_writes_through_replacement_parent(self):
        original = os.symlink
        external = self.parent/'external'
        external.mkdir()
        moved = self.parent/'moved-checkout'
        def race(target, path, **kwargs):
            self.root.rename(moved)
            original(external, self.root, target_is_directory=True)
            original(target, path, **kwargs)
        with patch.object(layout.os, 'symlink', side_effect=race):
            with self.assertRaises(RuntimeError): self.prepare()
        self.assertFalse((external/'toolchain').is_symlink())
        self.assertEqual(os.readlink(moved/'toolchain'), '../toolchain')

    def test_preparation_sources_are_bound_by_existing_regression_guard(self):
        import sys
        with patch.object(sys, 'path', [str(ROOT/'tools'), *sys.path]):
            guard_spec = importlib.util.spec_from_file_location('layout_source_guard', ROOT/'tools/verify_v2.py')
            guard = importlib.util.module_from_spec(guard_spec)
            guard_spec.loader.exec_module(guard)
        inventory = guard.hashes()
        for path in ('package.json', 'tools/prepare_consumer_toolchain_layout.py',
                     'tests/test_consumer_toolchain_layout.py', 'docs/EXPERIMENTAL_HOST_QUALIFICATION.md'):
            self.assertIn(path, inventory)

    def test_explicit_orchestration_and_ignore(self):
        import json
        package = json.loads((ROOT/'package.json').read_text())
        self.assertEqual(package['scripts']['test'],
            'python3 tools/prepare_consumer_toolchain_layout.py && python3 tools/verify_v2.py')
        self.assertIn('/toolchain', (ROOT/'.gitignore').read_text().splitlines())


if __name__ == '__main__': unittest.main()
