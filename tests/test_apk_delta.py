import copy
import json
import importlib.util
from pathlib import Path
import tempfile
import unittest
import zipfile

spec = importlib.util.spec_from_file_location('apk_delta', Path(__file__).resolve().parents[1] / 'tools/apk_delta.py')
delta = importlib.util.module_from_spec(spec)
spec.loader.exec_module(delta)


class APKDeltaTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.base, self.signed, self.output = [self.root / name for name in ['candidate.apk', 'signed.apk', 'output.apk']]
        for path, stamp in [(self.base, 1), (self.signed, 2)]:
            with zipfile.ZipFile(path, 'w') as archive:
                item = zipfile.ZipInfo('assets/model', (2026, 9, stamp, 0, 0, 0))
                archive.writestr(item, bytes(range(256)) * 9000)
                archive.writestr('META-INF/example', str(stamp))
        self.document = delta.make_delta(self.base, self.signed)

    def test_exact_reconstruction_with_large_reused_region(self):
        self.assertLess(self.document['literal_bytes'], 1000)
        delta.apply_delta(self.base, self.document, self.output)
        self.assertEqual(self.output.read_bytes(), self.signed.read_bytes())

    def test_wrong_candidate_rejected(self):
        with self.assertRaisesRegex(ValueError, 'candidate identity'):
            delta.apply_delta(self.signed, self.document, self.output)
        self.assertFalse(self.output.exists())

    def test_ci_catalog_produces_the_identical_verified_delta(self):
        index = self.root / 'candidate-index.json'
        index.write_text(json.dumps(delta.catalog(self.base)))
        portable = delta.make_delta(index, self.signed, from_catalog=True)
        self.assertEqual(portable, self.document)
        delta.apply_delta(self.base, portable, self.output)
        self.assertEqual(self.output.read_bytes(), self.signed.read_bytes())

    def test_corrupt_patch_preserves_previous_output(self):
        self.output.write_bytes(b'previous verified release')
        bad = copy.deepcopy(self.document)
        bad['target_sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'Signed APK identity'):
            delta.apply_delta(self.base, bad, self.output)
        self.assertEqual(self.output.read_bytes(), b'previous verified release')
        self.assertFalse(list(self.root.glob('.apk-delta-*')))

    def test_invalid_copy_bounds_rejected(self):
        for offset, size in [(-1, 1), (0, -1), (0, self.document['base_bytes'] + 1), (0.5, 1)]:
            bad = copy.deepcopy(self.document)
            bad['operations'] = [{'offset': offset, 'bytes': size}]
            with self.assertRaisesRegex(ValueError, 'copy bounds'):
                delta.apply_delta(self.base, bad, self.output)
        self.assertFalse(self.output.exists())
