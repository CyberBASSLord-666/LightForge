"""The pinned host JAR download cannot exhaust memory/disk or race publication."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
from io import BytesIO
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import bootstrap_testdeps as bootstrap


class Response(BytesIO):
    def __init__(self, content):
        super().__init__(content)
        self.received = 0

    def read(self, size=-1):
        if not 0 < size <= 1024 * 1024:
            raise AssertionError('unbounded read')
        result = super().read(size)
        self.received += len(result)
        return result


class HostDependencyDownload(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.destination = Path(self.temp.name) / 'test-json.jar'
        self.content = b'pinned host jar'
        for key, value in [('DEST', self.destination), ('SIZE', len(self.content)),
                           ('SHA', hashlib.sha256(self.content).hexdigest())]:
            mock = patch.object(bootstrap, key, value)
            mock.start()
            self.addCleanup(mock.stop)

    def run_download(self, response):
        with patch.object(bootstrap.urllib.request, 'urlopen', return_value=response) as opened:
            bootstrap.prepare()
        return opened

    def test_download_then_recheck_cache(self):
        opened = self.run_download(Response(self.content))
        opened.assert_called_once_with(bootstrap.URL, timeout=60)
        self.run_download(None).assert_not_called()
        self.assertEqual(self.destination.read_bytes(), self.content)
        self.destination.write_bytes(b'x' * len(self.content))
        self.run_download(Response(self.content)).assert_called_once()

    def test_oversize_fails_after_pin_plus_one_bytes(self):
        response = Response(self.content + b'x' * 100000)
        with self.assertRaisesRegex(RuntimeError, 'limit exceeded'):
            self.run_download(response)
        self.assertEqual(response.received, len(self.content) + 1)
        self.assertEqual(list(self.destination.parent.iterdir()), [])

    def test_corrupt_truncated_and_failed_downloads_preserve_cache(self):
        for data in [b'x' * len(self.content), self.content[:-1]]:
            self.destination.write_bytes(b'previous')
            with self.assertRaisesRegex(RuntimeError, 'checksum mismatch'):
                self.run_download(Response(data))
            self.assertEqual(self.destination.read_bytes(), b'previous')
            self.assertEqual(list(self.destination.parent.iterdir()), [self.destination])
        response = Response(self.content)
        response.read = lambda size: (_ for _ in ()).throw(TimeoutError('stalled'))
        with self.assertRaises(TimeoutError):
            self.run_download(response)
        self.assertEqual(self.destination.read_bytes(), b'previous')
        self.assertEqual(list(self.destination.parent.iterdir()), [self.destination])

    def test_slow_response_deadline(self):
        with patch.object(bootstrap.time, 'monotonic', side_effect=[0, 121]):
            with self.assertRaisesRegex(RuntimeError, 'limit exceeded'):
                self.run_download(Response(self.content))
        self.assertEqual(list(self.destination.parent.iterdir()), [])

    def test_concurrent_downloads_publish_only_complete_bytes(self):
        barrier = threading.Barrier(2)
        content = self.content
        class ConcurrentResponse(Response):
            def read(self, size=-1):
                if not self.received:
                    barrier.wait(timeout=5)
                return super().read(size)
        with patch.object(bootstrap.urllib.request, 'urlopen', side_effect=lambda *a, **k: ConcurrentResponse(content)):
            with ThreadPoolExecutor(max_workers=2) as workers:
                list(workers.map(lambda _: bootstrap.prepare(), range(2)))
        self.assertEqual(self.destination.read_bytes(), self.content)
        self.assertEqual(list(self.destination.parent.iterdir()), [self.destination])


if __name__ == '__main__':
    unittest.main()
