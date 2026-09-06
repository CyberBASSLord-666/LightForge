import hashlib
import importlib.util
import tempfile
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('restore', Path(__file__).with_name('restore.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class RestoreTest(unittest.TestCase):
    def fixture(self, root):
        (root / 'part').write_bytes(b'original')
        (root / 'output').write_bytes(b'preserve')
        sha = hashlib.sha256(b'original').hexdigest()
        return {'path': 'output', 'kind': 'source', 'bytes': 8, 'sha256': sha,
                'parts': [{'path': 'part', 'bytes': 8, 'sha256': sha}]}

    def test_restore_and_corruption_preservation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            item = self.fixture(root)
            module.restore(root, item)
            self.assertEqual((root / 'output').read_bytes(), b'original')
            (root / 'part').write_bytes(b'corrupt!')
            with self.assertRaises(ValueError): module.restore(root, item)
            self.assertEqual((root / 'output').read_bytes(), b'original')
            self.assertEqual(sorted(p.name for p in root.iterdir()), ['output', 'part'])

    def test_truncation_and_final_digest_preserve_output(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            item = self.fixture(root)
            (root / 'part').write_bytes(b'x')
            with self.assertRaises(ValueError): module.restore(root, item)
            self.assertEqual((root / 'output').read_bytes(), b'preserve')
            item = self.fixture(root)
            item['sha256'] = '0' * 64
            with self.assertRaises(ValueError): module.restore(root, item)
            self.assertEqual((root / 'output').read_bytes(), b'preserve')

    def test_paths_duplicates_and_size_limit(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            item = self.fixture(root)
            item['path'] = '../outside'
            with self.assertRaises(ValueError): module.restore(root, item)
            item = self.fixture(root)
            item['parts'] *= 2
            item['bytes'] = 16
            with self.assertRaises(ValueError): module.restore(root, item)
            item = self.fixture(root)
            item['bytes'] = item['parts'][0]['bytes'] = 8 * 1024 * 1024 + 1
            with self.assertRaises(ValueError): module.restore(root, item)
            self.assertEqual((root / 'output').read_bytes(), b'preserve')

if __name__ == '__main__': unittest.main()
