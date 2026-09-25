"""Reject unsafe archive/input trust boundaries without model execution."""
import importlib.util
import json
from pathlib import Path
import stat
import tempfile
import unittest
import warnings
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('deux_independent_auditor',
    ROOT / 'research/performance/2026-09-25/deux-full-source/verify_evidence.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class DeuxEvidenceAuditorTest(unittest.TestCase):
    def test_paths_reject_traversal_absolute_backslash_drive_and_ambiguity(self):
        for name in ('../x', '/x', 'C:/x', 'a\\b', 'a//b', 'a/./b', 'a/../b', '', 'x\x00y'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                audit.safe_relative(name)
        self.assertEqual(str(audit.safe_relative('qualification/cpu_all_plain/receipt.json')),
                         'qualification/cpu_all_plain/receipt.json')

    def test_json_rejects_duplicate_nonfinite_and_linked_input(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / 'input.json'
            for payload in ('{"x":1,"x":2}', '{"x":NaN}', '{"x":1e10000}'):
                path.write_text(payload)
                with self.assertRaises(ValueError):
                    audit.strict_json(path)
            path.write_text('{"x":1}')
            (root / 'linked.json').symlink_to(path)
            with self.assertRaises(ValueError):
                audit.strict_json(root / 'linked.json')
            with self.assertRaises(ValueError):
                audit.inventory(root)

    def test_archive_rejects_wrong_digest_duplicate_traversal_and_symlink(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for index, names in enumerate((['../escape'], ['run/x', 'run/x'], ['run/x'])):
                archive_path = root / f'bad-{index}.zip'
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore', UserWarning)
                    with zipfile.ZipFile(archive_path, 'w') as archive:
                        for name in names:
                            entry = zipfile.ZipInfo(name)
                            if index == 2:
                                entry.external_attr = (stat.S_IFLNK | 0o777) << 16
                            archive.writestr(entry, b'x')
                with self.assertRaises(ValueError):
                    audit.extract_zip(archive_path, audit.pin(archive_path), root / f'extracted-{index}')
            valid = root / 'valid.zip'
            with zipfile.ZipFile(valid, 'w') as archive:
                archive.writestr('run/x', b'original')
            with self.assertRaises(ValueError):
                audit.extract_zip(valid, dict(bytes=valid.stat().st_size, sha256='0' * 64), root / 'wrong-digest')
            restored = audit.extract_zip(valid, audit.pin(valid), root / 'valid-extracted')
            self.assertEqual((restored / 'x').read_bytes(), b'original')

    def test_authenticated_byte_loader_does_not_use_archived_pyc_or_foreign_dynamic_import(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'safe.py').write_text('RESULT = "source bytes"\n')
            (root / '__pycache__').mkdir()
            (root / '__pycache__/safe.cpython-311.pyc').write_bytes(b'not bytecode')
            self.assertEqual(audit.import_frozen(root, 'safe.py').RESULT, 'source bytes')
            (root / 'bad.py').write_text(
                'import importlib.util\n'
                'importlib.util.spec_from_file_location("foreign", "/not-an-authenticated-helper.py")\n')
            with self.assertRaises(ValueError):
                audit.import_frozen(root, 'bad.py')

    def test_completed_archive_may_omit_empty_active_trace_directory_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = root / 'cpu_all_profiled_active_traces'
            audit.verify_no_active_traces(directory)
            directory.mkdir()
            audit.verify_no_active_traces(directory)
            (directory / 'front_unmatched.json').write_text('[]')
            with self.assertRaises(ValueError):
                audit.verify_no_active_traces(directory)
            (directory / 'front_unmatched.json').unlink()
            directory.rmdir()
            directory.symlink_to(root, target_is_directory=True)
            with self.assertRaises(ValueError):
                audit.verify_no_active_traces(directory)


if __name__ == '__main__':
    unittest.main()
