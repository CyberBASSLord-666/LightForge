"""Unsafe evidence must fail before source imports or native execution."""
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('verify_session_reuse', ROOT/'tools/game_benchmark/verify_session_reuse_evidence.py')
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)


class VerifySessionReuseEvidenceTest(unittest.TestCase):
    def test_unsafe_paths_rejected(self):
        for name in ('../x', '/x', 'a/../x', 'a//x', './x', 'C:/x', 'a\\x', ''):
            with self.subTest(name=name), self.assertRaises(ValueError):
                verify.safe_relative(name)

    def test_duplicate_or_nonfinite_json_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'x.json'
            for value in ('{"a":1,"a":2}', '{"a":NaN}', '{"a":1e999}'):
                path.write_text(value)
                with self.assertRaises(ValueError):
                    verify.strict_json(path)

    def test_symlink_path_and_inventory_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root/'real').write_text('x'); (root/'link').symlink_to(root/'real')
            with self.assertRaises(ValueError):
                verify.safe_file(root, 'link')
            with self.assertRaises(ValueError):
                verify.tree_inventory(root)

    def test_zip_path_traversal_never_extracted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); archive = root/'bad.zip'; output = root/'out'; output.mkdir()
            with zipfile.ZipFile(archive, 'w') as stream:
                stream.writestr('../escape', 'bad')
            args = SimpleNamespace(zip=archive, expected_size=archive.stat().st_size,
                expected_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(), output_dir=output, max_uncompressed_bytes=1000)
            with self.assertRaises(ValueError):
                verify.extract_zip(args)
            self.assertFalse((root/'escape').exists())

    def test_archive_inventory_rejects_extra_or_changed_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root/'data').write_text('safe')
            manifest = dict(schema='lightforge.game-session-reuse-archive.v1', executionSourceCommit='a'*40,
                executionSourceTree='b'*40, runDirectory=root.name, qualityApproved=False,
                target75Proven=False, releaseAuthorized=False, files=[])
            (root/'archive-manifest.json').write_text(json.dumps(manifest))
            with self.assertRaises(ValueError):
                verify.verify_archive_inventory(root, verify.tree_inventory(root), 'a'*40, 'b'*40, True)

    def test_serial_trace_identity_requires_one_process_and_thread(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def event(pid=10, tid=11):
                return dict(cat='Session', name='model_run', ph='X', ts=100, dur=5, pid=pid, tid=tid)
            (root/'a.json').write_text(json.dumps([event()]))
            (root/'b.json').write_text(json.dumps([event()]))
            self.assertEqual(verify.validate_trace_process_identity(root), dict(processId=10, callerThreadId=11))
            for bad in (event(pid=12), event(tid=12), {k:v for k,v in event().items() if k!='pid'}):
                (root/'b.json').write_text(json.dumps([bad]))
                with self.assertRaises(ValueError):
                    verify.validate_trace_process_identity(root)


if __name__ == '__main__':
    unittest.main()
