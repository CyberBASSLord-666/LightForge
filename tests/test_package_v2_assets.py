"""Signed-package asset selection, independent of native/signing gate fixtures."""
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / 'tools') not in sys.path:
    sys.path.insert(0, str(ROOT / 'tools'))
SPEC = importlib.util.spec_from_file_location('package_v2_assets', ROOT / 'tools/package_v2.py')
package = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(package)


class PackageV2AssetTest(unittest.TestCase):
    def fixture(self, root):
        files = {
            'index.html': b'current app',
            'analysis/worker.js': b'current analysis',
            'analysis/models/beat-this-large.onnx': b'current rhythm graph',
            'analysis/models/BeatNet-LICENSE.txt': b'retained notice',
            'analysis/models/beatnet-v1.onnx': b'research-only graph',
            'preview/vehicle-preview.js': b'compiled renderer',
            'preview/vendor/THREE-LICENSE.txt': b'compiled renderer notice',
            'preview/src/vehicle-preview.js': b'build source',
        }
        for relative, data in files.items():
            path = root / 'web' / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        (root / 'version.json').write_text(json.dumps({'name': '2.4.3', 'code': 20403}))
        (root / 'dist').mkdir()
        (root / 'build').mkdir()
        (root / 'build/signature-verification.txt').write_text(
            'Signer #1 certificate SHA-256 digest: ' + package.SIGNING_SHA256 + '\n')
        return files

    def archive(self, root, files, *, extra=(), missing=(), altered=None):
        excluded = {'analysis/models/beatnet-v1.onnx', 'preview/src/vehicle-preview.js'}
        apk = root / 'dist/LightForge-2.4.3.apk'
        with zipfile.ZipFile(apk, 'w') as archive:
            for name in (set(files) - excluded | set(extra)) - set(missing):
                archive.writestr('assets/' + name, (altered or {}).get(name, files[name]))
        receipt = {'version_name': '2.4.3', 'version_code': 20403,
                   'sha256': hashlib.sha256(apk.read_bytes()).hexdigest(),
                   'update_compatible': True,
                   'signing_certificate_sha256': package.SIGNING_SHA256}
        apk.with_suffix('.apk.json').write_text(json.dumps(receipt))
        return apk

    def run_package(self, root):
        # Gate/signature/native verification has its own suites; this fixture
        # isolates the actual main() source/ZIP inventory and copying behavior.
        with patch.object(package, 'ROOT', root), \
                patch.object(package, 'release_gate_names', return_value=[]), \
                patch.object(package, 'verify_native_libraries'), \
                contextlib.redirect_stdout(io.StringIO()):
            package.main()

    def test_signed_packaging_uses_same_precise_exclusions_as_staging(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            files = self.fixture(root)
            apk = self.archive(root, files)
            self.run_package(root)
            self.assertEqual((root / 'output' / apk.name).read_bytes(), apk.read_bytes())
            report = json.loads((root / 'release-verification.json').read_text())
            self.assertEqual(report['apk_source_assets_matched'], 6)
            self.assertEqual(report['signing_certificate_sha256'], package.SIGNING_SHA256)

    def test_extra_research_asset_and_missing_runtime_or_notice_fail(self):
        cases = [({'extra': ['analysis/models/beatnet-v1.onnx']}, 'inventory'),
                 ({'extra': ['preview/src/vehicle-preview.js']}, 'inventory'),
                 ({'missing': ['analysis/worker.js']}, 'inventory'),
                 ({'missing': ['preview/vendor/THREE-LICENSE.txt']}, 'inventory'),
                 ({'altered': {'preview/vehicle-preview.js': b'stale renderer'}}, 'stale source')]
        for options, reason in cases:
            with self.subTest(options=options), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                files = self.fixture(root)
                self.archive(root, files, **options)
                with self.assertRaisesRegex(SystemExit, reason):
                    self.run_package(root)
                self.assertFalse((root / 'output').exists())

    def test_excluded_folder_does_not_allow_symlink_source(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            files = self.fixture(root)
            self.archive(root, files)
            target = root / 'web/preview/src/link.js'
            target.symlink_to(root / 'web/index.html')
            with self.assertRaisesRegex(ValueError, 'Symlink'):
                self.run_package(root)
            self.assertFalse((root / 'output').exists())


if __name__ == '__main__':
    unittest.main()
