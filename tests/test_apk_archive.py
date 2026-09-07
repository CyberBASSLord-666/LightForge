#!/usr/bin/env python3
"""Regression coverage for an aapt2 success with a truncated resource APK."""
import importlib.util
import hashlib
import json
import struct
from pathlib import Path
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('apk_archive', ROOT / 'tools/apk_archive.py')
apk_archive = importlib.util.module_from_spec(spec)
spec.loader.exec_module(apk_archive)


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.assets = self.root / 'assets'
        self.assets.mkdir()
        (self.assets / 'index.html').write_bytes(b'<html>Current assets</html>')
        self.dex = self.root / 'dex'
        self.dex.mkdir()
        (self.dex / 'classes.dex').write_bytes(b'dex\n035\x00fixture')
        self.resources = self.root / 'resources.apk'
        with zipfile.ZipFile(self.resources, 'w') as archive:
            archive.writestr('AndroidManifest.xml', b'fixture manifest')
            archive.writestr('resources.arsc', b'fixture resources')
            archive.write(self.assets / 'index.html', 'assets/index.html')
        self.output = self.root / 'unsigned.apk'

    def test_valid_assembly_preserves_resources_and_adds_dex(self):
        apk_archive.assemble_apk(self.resources, self.dex, self.output, self.assets)
        names = apk_archive.validate_apk(self.output, self.assets, require_dex=True)
        self.assertEqual(names, {'AndroidManifest.xml', 'resources.arsc',
                                 'assets/index.html', 'classes.dex'})

    def test_truncated_central_directory_stops_before_output(self):
        data = self.resources.read_bytes()
        self.resources.write_bytes(data[:-64])
        with self.assertRaises(zipfile.BadZipFile):
            apk_archive.assemble_apk(self.resources, self.dex, self.output, self.assets)
        self.assertFalse(self.output.exists())

    def test_corrupt_asset_crc_stops_before_output(self):
        data = self.resources.read_bytes()
        self.resources.write_bytes(data.replace(b'Current assets', b'Changed assets', 1))
        with self.assertRaisesRegex(ValueError, 'integrity'):
            apk_archive.assemble_apk(self.resources, self.dex, self.output, self.assets)
        self.assertFalse(self.output.exists())

    def test_stale_or_missing_assets_are_rejected(self):
        (self.assets / 'index.html').write_bytes(b'<html>New source</html>')
        with self.assertRaisesRegex(ValueError, 'asset bytes differ'):
            apk_archive.validate_apk(self.resources, self.assets)
        (self.assets / 'other.js').write_bytes(b'new asset')
        with self.assertRaisesRegex(ValueError, 'asset set differs'):
            apk_archive.validate_apk(self.resources, self.assets)

    def test_invalid_dex_cleans_partial_output(self):
        (self.dex / 'classes.dex').write_bytes(b'not Android bytecode')
        with self.assertRaisesRegex(ValueError, 'Invalid DEX'):
            apk_archive.assemble_apk(self.resources, self.dex, self.output, self.assets)
        self.assertFalse(self.output.exists())

    def test_aapt_compression_scratch_is_not_a_distributable_asset(self):
        (self.assets / '.model.onnx.part').write_bytes(b'incomplete compression scratch')
        apk_archive.assemble_apk(self.resources, self.dex, self.output, self.assets)
        self.assertNotIn('assets/.model.onnx.part', zipfile.ZipFile(self.output).namelist())

    def test_existing_output_is_not_replaced(self):
        self.output.write_bytes(b'previous artifact')
        with self.assertRaises(FileExistsError):
            apk_archive.assemble_apk(self.resources, self.dex, self.output, self.assets)
        self.assertEqual(self.output.read_bytes(), b'previous artifact')

    def native_fixture(self):
        native = self.root / 'jni'
        library = native / 'arm64-v8a/libonnxruntime.so'
        library.parent.mkdir(parents=True)
        elf = bytearray(120)
        elf[:16] = b'\x7fELF' + bytes([2, 1, 1]) + bytes(9)
        struct.pack_into('<Q', elf, 32, 64)
        struct.pack_into('<HH', elf, 54, 56, 1)
        struct.pack_into('<I', elf, 64, 1)
        struct.pack_into('<Q', elf, 112, 16384)
        library.write_bytes(elf + b'verified-native-runtime')
        manifest = self.root / 'runtime.json'
        manifest.write_text(json.dumps({'files': {'jni/arm64-v8a/libonnxruntime.so': {
            'bytes': library.stat().st_size,
            'sha256': hashlib.sha256(library.read_bytes()).hexdigest()}}}))
        return native, library, manifest

    def test_jni_assembly_preserves_verified_native_bytes_uncompressed(self):
        native, library, manifest = self.native_fixture()
        apk_archive.assemble_apk(self.resources, self.dex, self.output, self.assets, native, manifest)
        apk_archive.validate_apk(self.output, self.assets, True, manifest)
        with zipfile.ZipFile(self.output) as archive:
            self.assertEqual(archive.read('lib/arm64-v8a/libonnxruntime.so'), library.read_bytes())
            self.assertEqual(archive.getinfo('lib/arm64-v8a/libonnxruntime.so').compress_type, zipfile.ZIP_STORED)
        with self.assertRaisesRegex(ValueError, 'inventory'):
            apk_archive.validate_apk(self.output, self.assets, True)

    def test_corrupt_or_extra_jni_cannot_be_published(self):
        native, library, manifest = self.native_fixture()
        library.write_bytes(library.read_bytes().replace(b'verified', b'modified'))
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            apk_archive.assemble_apk(self.resources, self.dex, self.output, self.assets, native, manifest)
        self.assertFalse(self.output.exists())
        (native / 'arm64-v8a/unreviewed.so').write_bytes(b'\x7fELFextra')
        with self.assertRaisesRegex(ValueError, 'inventory'):
            apk_archive.assemble_apk(self.resources, self.dex, self.output, self.assets, native, manifest)
        self.assertFalse(self.output.exists())

    def test_missing_native_library_cannot_be_packaged(self):
        native, library, manifest = self.native_fixture()
        library.unlink()
        with self.assertRaisesRegex(ValueError, 'inventory'):
            apk_archive.assemble_apk(self.resources, self.dex, self.output, self.assets, native, manifest)
        self.assertFalse(self.output.exists())

    def test_native_elf_requires_16k_load_alignment(self):
        native, library, manifest = self.native_fixture()
        payload = bytearray(library.read_bytes())
        struct.pack_into('<Q', payload, 112, 4096)
        library.write_bytes(payload)
        metadata = json.loads(manifest.read_text())
        metadata['files']['jni/arm64-v8a/libonnxruntime.so']['sha256'] = hashlib.sha256(payload).hexdigest()
        manifest.write_text(json.dumps(metadata))
        with self.assertRaisesRegex(ValueError, '16 KiB'):
            apk_archive.assemble_apk(self.resources, self.dex, self.output, self.assets, native, manifest)
        self.assertFalse(self.output.exists())


if __name__ == '__main__':
    unittest.main()
