"""Pinned tool downloads stay bounded, atomic and independently verifiable."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from io import BytesIO, StringIO
from pathlib import Path
import hashlib
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import bootstrap_toolchain as bootstrap


class BoundedResponse(BytesIO):
    def read(self, size=-1):
        if not 0 < size <= 1024 * 1024:
            raise AssertionError('download must use bounded reads')
        return super().read(size)


class ToolchainDownloadTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.destination = Path(self.directory.name)
        self.patch = patch.object(bootstrap, 'DEST', self.destination)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.content = b'original pinned archive' * 120000
        self.package = dict(name='fixture.zip', url='https://example.invalid/fixture.zip',
                            size=len(self.content), sha256=hashlib.sha256(self.content).hexdigest())
        self.path = self.destination / 'downloads/fixture.zip'

    def download(self, response):
        with patch.object(bootstrap.urllib.request, 'urlopen', return_value=response) as opened, \
                redirect_stdout(StringIO()):
            result = bootstrap.download(self.package)
        return result, opened

    def assert_no_partial(self):
        self.assertEqual(list(self.path.parent.glob('*.part')), [])

    def test_cold_download_streams_and_warm_download_does_not_fetch(self):
        result, opened = self.download(BoundedResponse(self.content))
        self.assertEqual(result, (self.package, self.path))
        opened.assert_called_once_with(self.package['url'], timeout=240)
        self.assertEqual(self.path.read_bytes(), self.content)
        _, opened = self.download(None)
        opened.assert_not_called()
        self.assert_no_partial()

    def test_same_size_corrupt_cache_is_not_trusted(self):
        self.path.parent.mkdir()
        self.path.write_bytes(b'x' * len(self.content))
        _, opened = self.download(BoundedResponse(self.content))
        opened.assert_called_once()
        self.assertEqual(bootstrap.digest(self.path), self.package['sha256'])
        self.assert_no_partial()

    def test_wrong_hash_short_and_oversized_responses_never_publish(self):
        for content in (b'x' * len(self.content), self.content[:-1], self.content + b'x'):
            with self.subTest(size=len(content)):
                with self.assertRaisesRegex(RuntimeError, 'Download integrity failure'):
                    self.download(BoundedResponse(content))
                self.assertFalse(self.path.exists())
                self.assert_no_partial()

    def test_failed_replacement_preserves_previous_archive(self):
        self.path.parent.mkdir()
        self.path.write_bytes(b'previous wrong version')
        with self.assertRaisesRegex(RuntimeError, 'Download integrity failure'):
            self.download(BoundedResponse(b'bad download'))
        self.assertEqual(self.path.read_bytes(), b'previous wrong version')
        self.assert_no_partial()

    def test_interrupted_download_removes_partial_file(self):
        class Interrupted(BoundedResponse):
            def read(self, size=-1):
                if self.tell():
                    raise OSError('connection interrupted')
                return super().read(size)
        with self.assertRaisesRegex(OSError, 'connection interrupted'):
            self.download(Interrupted(self.content))
        self.assertFalse(self.path.exists())
        self.assert_no_partial()

    def test_concurrent_downloads_have_unique_staging_files(self):
        barrier = threading.Barrier(2)
        def response(*args, **kwargs):
            barrier.wait(timeout=5)
            return BoundedResponse(self.content)
        with patch.object(bootstrap.urllib.request, 'urlopen', side_effect=response), \
                redirect_stdout(StringIO()), ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(bootstrap.download, [self.package, self.package]))
        self.assertEqual(results, [(self.package, self.path)] * 2)
        self.assertEqual(bootstrap.digest(self.path), self.package['sha256'])
        self.assert_no_partial()


if __name__ == '__main__':
    unittest.main()
