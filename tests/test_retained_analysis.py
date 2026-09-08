"""Evidence retention must reject changed measured bytes and unauthenticated metadata."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'tools/verify_retained_analysis.py'
spec = importlib.util.spec_from_file_location('retained_analysis', SOURCE)
retention = importlib.util.module_from_spec(spec)
spec.loader.exec_module(retention)


class RetainedAnalysisTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.archive = 'qa/release-2.2.2/prior-version-2.2.1.json'
        self.prior = 'qa/release-2.2.1/analysis-verification.json'
        self.write('tools/verify_retained_analysis.py', SOURCE.read_bytes())
        self.write('web/analysis/worker.js', b'runFullModel();\n')
        self.write('web/analysis/model.onnx', bytes(range(256)) * 4)
        self.json(self.archive, {'name': '2.2.1', 'code': 20201})
        self.json('version.json', {'name': '2.2.2', 'code': 20202})
        self.evidence = {
            'release': '2.2.1', 'passed': True, 'errors': [],
            'source_hashes': {name: self.sha(name) for name in ['web/analysis/worker.js', 'web/analysis/model.onnx']}
        }
        self.evidence['source_hashes']['version.json'] = self.sha(self.archive)
        self.json(self.prior, self.evidence)

    def write(self, name, data):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def json(self, name, data):
        self.write(name, (json.dumps(data, indent=2) + '\n').encode())

    def sha(self, name):
        return hashlib.sha256((self.root / name).read_bytes()).hexdigest()

    def retain(self):
        return retention.retained_receipt(self.root, '2.2.1', self.archive)

    def test_explicit_metadata_migration_keeps_old_evidence_and_labels_retention(self):
        before = (self.root / self.prior).read_bytes()
        result = self.retain()
        self.assertTrue(result['passed'])
        self.assertEqual(result['release'], '2.2.2')
        self.assertIn('not a fresh', result['scope'])
        self.assertEqual(result['metadata_migrations'][0]['prior_sha256'], self.sha(self.archive))
        self.assertEqual(result['source_hashes']['version.json'], self.sha('version.json'))
        self.assertEqual(result['retained_evidence']['sha256'], hashlib.sha256(before).hexdigest())
        self.assertEqual((self.root / self.prior).read_bytes(), before)

    def test_changed_algorithm_or_same_size_model_is_rejected(self):
        for name in ['web/analysis/worker.js', 'web/analysis/model.onnx']:
            with self.subTest(name=name):
                original = (self.root / name).read_bytes()
                self.write(name, bytes([original[0] ^ 1]) + original[1:])
                with self.assertRaisesRegex(ValueError, 'Measured model/source changed'):
                    self.retain()
                self.write(name, original)

    def test_version_change_requires_explicit_predecessor_bytes(self):
        with self.assertRaisesRegex(ValueError, 'Measured model/source changed: version.json'):
            retention.retained_receipt(self.root, '2.2.1')
        self.write(self.archive, (self.root / self.archive).read_bytes() + b' ')
        with self.assertRaisesRegex(ValueError, 'prior evidence hash'):
            self.retain()

    def test_wrong_release_failed_receipt_and_error_list_are_rejected(self):
        for field, value in [('release', '2.2.0'), ('passed', False), ('passed', 1), ('errors', ['benchmark failed'])]:
            with self.subTest(field=field, value=value):
                damaged = dict(self.evidence, **{field: value})
                self.json(self.prior, damaged)
                with self.assertRaises(ValueError):
                    self.retain()

    def test_current_metadata_rejects_extras_missing_boolean_and_invalid_values(self):
        for value in [{'name': '2.2.2', 'code': 20202, 'model': 'tiny'},
                      {'name': '2.2.2'}, {'name': '02.2.2', 'code': 20202},
                      {'name': '2.2.2', 'code': True}, {'name': '2.2.2', 'code': 0},
                      {'name': '2.2.2', 'code': 2100000001}, ['2.2.2', 20202]]:
            with self.subTest(value=value):
                self.json('version.json', value)
                with self.assertRaises(ValueError):
                    self.retain()

    def test_metadata_must_advance_version_name_and_android_code(self):
        for value in [{'name': '2.2.1', 'code': 20202}, {'name': '2.2.0', 'code': 20202},
                      {'name': '2.2.2', 'code': 20201}, {'name': '2.2.2', 'code': 20200}]:
            with self.subTest(value=value):
                self.json('version.json', value)
                with self.assertRaises(ValueError):
                    self.retain()

    def test_predecessor_schema_and_release_are_validated_even_with_matching_hash(self):
        for value in [{'name': '2.2.0', 'code': 20200}, {'name': '2.2.1', 'code': True},
                      {'name': '2.2.1', 'code': 20201, 'quality': 'changed'}]:
            with self.subTest(value=value):
                self.json(self.archive, value)
                damaged = json.loads(json.dumps(self.evidence))
                damaged['source_hashes']['version.json'] = self.sha(self.archive)
                self.json(self.prior, damaged)
                with self.assertRaises(ValueError):
                    self.retain()

    def test_missing_file_traversal_and_empty_measurement_set_are_rejected(self):
        for name in ['web/analysis/missing.onnx', '../outside', '/etc/passwd']:
            with self.subTest(name=name):
                damaged = json.loads(json.dumps(self.evidence))
                damaged['source_hashes'][name] = '0' * 64
                self.json(self.prior, damaged)
                with self.assertRaises(ValueError):
                    self.retain()
        self.json(self.prior, dict(self.evidence, source_hashes={'version.json': self.sha(self.archive)}))
        with self.assertRaisesRegex(ValueError, 'no measured sources'):
            self.retain()

    def test_cli_failure_preserves_current_receipt_and_original_evidence(self):
        output = 'qa/release-2.2.2/analysis-verification.json'
        self.json(output, {'retained': 'previous complete result'})
        before = (self.root / output).read_bytes()
        old = (self.root / self.prior).read_bytes()
        self.write('web/analysis/worker.js', b'changed();')
        result = subprocess.run([sys.executable, '-O', str(self.root / 'tools/verify_retained_analysis.py'),
                                 '--from-release', '2.2.1', '--prior-version-file', self.archive],
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Measured model/source changed', result.stderr)
        self.assertEqual((self.root / output).read_bytes(), before)
        self.assertEqual((self.root / self.prior).read_bytes(), old)


if __name__ == '__main__':
    unittest.main()
