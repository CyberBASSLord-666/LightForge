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


class ManagedInstallationTest(unittest.TestCase):
    def setUp(self):
        import zipfile
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.destination = Path(self.directory.name)
        self.patch = patch.object(bootstrap, 'DEST', self.destination)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.archive = self.destination / 'fixture.zip'
        with zipfile.ZipFile(self.archive, 'w') as archive:
            archive.writestr('jdk/bin/javac', b'compiler')
            archive.writestr('jdk/lib/runtime', b'runtime')
        self.package = dict(name='fixture.zip', url='https://example.invalid/fixture.zip',
                            size=self.archive.stat().st_size, sha256=bootstrap.digest(self.archive),
                            source='jdk', target='jdk17', check='bin/javac')
        self.target = self.destination / 'jdk17'

    def install(self):
        with redirect_stdout(StringIO()):
            bootstrap.install(self.package, self.archive)

    def test_fresh_and_verified_reuse(self):
        self.install()
        before = bootstrap.inventory(self.target)
        self.install()
        self.assertEqual(before, bootstrap.inventory(self.target))

    def test_legacy_existing_compiler_is_preserved_and_rejected(self):
        (self.target / 'bin').mkdir(parents=True)
        (self.target / 'bin/javac').write_bytes(b'legacy compiler')
        with self.assertRaisesRegex(RuntimeError, 'Unmanaged or differently pinned'):
            self.install()
        self.assertEqual((self.target / 'bin/javac').read_bytes(), b'legacy compiler')

    def test_different_pin_is_preserved_and_rejected(self):
        self.install()
        self.package['url'] += '?new-pin'
        with self.assertRaisesRegex(RuntimeError, 'differently pinned'):
            self.install()
        self.assertEqual((self.target / 'bin/javac').read_bytes(), b'compiler')

    def test_changed_deleted_extra_file_and_mode_are_rejected(self):
        self.install()
        original = self.target / 'lib/runtime'
        for mutation in ('content', 'missing', 'extra', 'mode'):
            with self.subTest(mutation=mutation):
                original.write_bytes(b'runtime')
                original.chmod(0o644)
                extra = self.target / 'extra'
                extra.unlink(missing_ok=True)
                if mutation == 'content':
                    original.write_bytes(b'changed')
                elif mutation == 'missing':
                    original.unlink()
                elif mutation == 'extra':
                    extra.write_bytes(b'extra')
                else:
                    original.chmod(0o755)
                with self.assertRaisesRegex(RuntimeError, 'Changed managed installation'):
                    self.install()

    def test_target_and_receipt_symlinks_are_rejected(self):
        self.install()
        alternate = self.destination / 'alternate'
        self.target.rename(alternate)
        self.target.symlink_to(alternate, target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, 'Unmanaged'):
            self.install()
        self.target.unlink()
        alternate.rename(self.target)
        receipt = self.target / bootstrap.INSTALL_RECEIPT
        saved = self.destination / 'saved-receipt'
        receipt.rename(saved)
        receipt.symlink_to(saved)
        with self.assertRaisesRegex(RuntimeError, 'Unmanaged'):
            self.install()

    def test_changed_root_mode_is_rejected(self):
        self.install()
        self.target.chmod(0o777)
        with self.assertRaisesRegex(RuntimeError, 'Changed managed installation'):
            self.install()

    def test_symlink_ancestor_cannot_publish_outside_destination(self):
        with tempfile.TemporaryDirectory() as external:
            ancestor = self.destination / 'nested'
            ancestor.symlink_to(external, target_is_directory=True)
            self.package['target'] = 'nested/jdk17'
            with self.assertRaisesRegex(RuntimeError, 'Unsafe installation ancestor'):
                self.install()
            self.assertEqual(list(Path(external).iterdir()), [])

    def test_file_ancestor_and_unsafe_target_are_rejected(self):
        (self.destination / 'file').write_bytes(b'preserve')
        for target in ('file/jdk17', '../escape', '/absolute', '.'):
            with self.subTest(target=target):
                self.package['target'] = target
                with self.assertRaisesRegex(RuntimeError, 'Unsafe installation'):
                    self.install()
        self.assertEqual((self.destination / 'file').read_bytes(), b'preserve')

    def test_invalid_receipt_is_preserved_and_rejected(self):
        self.install()
        receipt = self.target / bootstrap.INSTALL_RECEIPT
        receipt.write_text('{not-json')
        with self.assertRaisesRegex(RuntimeError, 'Unmanaged'):
            self.install()
        self.assertEqual(receipt.read_text(), '{not-json')

    def test_publisher_and_bootstrap_share_the_jdk_pin(self):
        package = next(p for p in bootstrap.PACKAGES if p['target'] == 'jdk17')
        publisher = (ROOT / '.github/workflows/publish-release.yml').read_text()
        for field in ('url', 'sha256', 'size', 'source'):
            self.assertIn(str(package[field]), publisher)

    def test_corrupted_archive_cannot_install(self):
        self.archive.write_bytes(b'bad archive')
        with self.assertRaisesRegex(RuntimeError, 'Install archive integrity failure'):
            self.install()
        self.assertFalse(self.target.exists())

    def test_concurrent_installers_reuse_one_complete_installation(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda _: bootstrap.install(self.package, self.archive), range(2)))
        self.install()
        self.assertFalse((self.target / 'jdk').exists())


if __name__ == '__main__':
    unittest.main()
