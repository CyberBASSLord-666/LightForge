"""Native dependency responses are bounded before publishing pinned bytes."""
import hashlib
from io import BytesIO
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import bootstrap_native_runtime as bootstrap


class Response(BytesIO):
    def __init__(self, data):
        super().__init__(data)
        self.received = 0

    def read(self, size=-1):
        if not 0 < size <= 1024 * 1024:
            raise AssertionError('unbounded read')
        result = super().read(size)
        self.received += len(result)
        return result


class NativeRuntimeDownloads(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        archive = BytesIO()
        with zipfile.ZipFile(archive, 'w') as output:
            output.writestr('classes.jar', b'pinned jar')
        self.content = archive.getvalue()
        item = {'name': 'android.aar', 'url': 'https://example.invalid/android.aar',
                'bytes': len(self.content), 'sha256': hashlib.sha256(self.content).hexdigest()}
        self.manifest = self.root / 'manifest.json'
        self.manifest.write_text(json.dumps({'android': item, 'host': dict(item, name='host.jar'), 'files': {}}))
        self.destination = self.root / 'downloads'
        for target, value in [('DEST', self.destination), ('MANIFEST', self.manifest)]:
            mock = patch.object(bootstrap, target, value)
            mock.start()
            self.addCleanup(mock.stop)

    def prepare(self, response):
        with patch.object(bootstrap.urllib.request, 'urlopen', return_value=response):
            return bootstrap.prepare()

    def test_valid_download_and_cache_reuse(self):
        with patch.object(bootstrap.urllib.request, 'urlopen', side_effect=lambda *a, **k: Response(self.content)) as opened:
            bootstrap.prepare()
            self.assertEqual(opened.call_count, 2)
            bootstrap.prepare(check=True)
            bootstrap.prepare()
            self.assertEqual(opened.call_count, 2)
            for call in opened.call_args_list:
                self.assertEqual(call.kwargs['timeout'], 120)
        self.assertEqual((self.destination / 'android.aar').read_bytes(), self.content)

    def test_oversized_response_stops_at_pin_plus_one(self):
        response = Response(self.content + b'x' * 100000)
        with self.assertRaisesRegex(RuntimeError, 'limit exceeded'):
            self.prepare(response)
        self.assertEqual(response.received, len(self.content) + 1)
        self.assertEqual(list(self.destination.iterdir()), [])

    def test_corruption_and_truncation_never_publish(self):
        for data in [self.content[:-1], b'x' * len(self.content)]:
            with self.subTest(size=len(data)), self.assertRaisesRegex(RuntimeError, 'integrity failure'):
                self.prepare(Response(data))
            self.assertEqual(list(self.destination.iterdir()), [])

    def test_timeout_cleans_temporary_and_preserves_old_cache(self):
        self.destination.mkdir()
        old = self.destination / 'android.aar'
        old.write_bytes(b'old invalid cache')
        response = Response(self.content)
        response.read = lambda size: (_ for _ in ()).throw(TimeoutError('stalled response'))
        with self.assertRaises(TimeoutError):
            self.prepare(response)
        self.assertEqual(old.read_bytes(), b'old invalid cache')
        self.assertEqual(list(self.destination.iterdir()), [old])

    def test_total_deadline_rejects_slow_drip(self):
        with patch.object(bootstrap.time, 'monotonic', side_effect=[0, 601]):
            with self.assertRaisesRegex(RuntimeError, 'limit exceeded'):
                self.prepare(Response(self.content))
        self.assertEqual(list(self.destination.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
