#!/usr/bin/env python3
"""Validate linked Android resources before adding dex to a real ZIP archive."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import shutil
import struct
import zipfile

CHUNK_BYTES = 1024 * 1024


def streams_equal(first, second):
    while True:
        chunk = first.read(CHUNK_BYTES)
        if chunk != second.read(CHUNK_BYTES):
            return False
        if not chunk:
            return True


def verify_elf_page_alignment(stream):
    """Require the pinned ELF load segments to support Android 16 KiB pages."""
    header = stream.read(64)
    if len(header) != 64 or header[:4] != b'\x7fELF' or header[4] not in (1, 2) or header[5] not in (1, 2):
        raise ValueError('Invalid native ELF header')
    bits, endian = header[4], '<' if header[5] == 1 else '>'
    word = 'Q' if bits == 2 else 'I'
    offset = struct.unpack_from(endian + word, header, 32 if bits == 2 else 28)[0]
    stride, count = struct.unpack_from(endian + 'HH', header, 54 if bits == 2 else 42)
    minimum = 56 if bits == 2 else 32
    if stride < minimum or not count or count > 1024:
        raise ValueError('Invalid native ELF program headers')
    loaded = 0
    for index in range(count):
        stream.seek(offset + index * stride)
        segment = stream.read(minimum)
        if len(segment) != minimum:
            raise ValueError('Truncated native ELF program header')
        if struct.unpack_from(endian + 'I', segment)[0] != 1:
            continue
        loaded += 1
        alignment = struct.unpack_from(endian + word, segment, 48 if bits == 2 else 28)[0]
        file_offset = struct.unpack_from(endian + word, segment, 8 if bits == 2 else 4)[0]
        address = struct.unpack_from(endian + word, segment, 16 if bits == 2 else 8)[0]
        if alignment < 16384 or alignment & (alignment - 1) or (file_offset - address) % 16384:
            raise ValueError('Native ELF load segment does not support 16 KiB pages')
    if not loaded:
        raise ValueError('Native ELF contains no load segments')


def verify_native_libraries(archive, native_manifest=None):
    """Accept exactly the pinned JNI payload, including its ELF identity."""
    expected = {}
    if native_manifest is not None:
        manifest = json.loads(Path(native_manifest).read_text())
        expected = {'lib/' + name.removeprefix('jni/'): entry
                    for name, entry in manifest['files'].items() if name.startswith('jni/')}
        if not expected:
            raise ValueError('Native runtime manifest contains no JNI libraries')
    actual = {name for name in archive.namelist() if name.startswith('lib/') and not name.endswith('/')}
    if actual != set(expected):
        raise ValueError('APK native library inventory differs from pinned runtime')
    for name, entry in expected.items():
        if archive.getinfo(name).file_size != entry['bytes']:
            raise ValueError('APK native library size mismatch: ' + name)
        with archive.open(name) as stream:
            verify_elf_page_alignment(stream)
        with archive.open(name) as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != entry['sha256']:
                raise ValueError('APK native library hash mismatch: ' + name)


def validate_apk(path, assets, require_dex=False, native_manifest=None):
    """Read mode rejects truncated archives; verify every CRC and staged asset."""
    path, assets = Path(path), Path(assets)
    with zipfile.ZipFile(path, 'r') as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError('Duplicate APK archive entries')
        required = {'AndroidManifest.xml', 'resources.arsc', 'assets/index.html'}
        if require_dex:
            required.add('classes.dex')
        missing = required - set(names)
        if missing:
            raise ValueError('APK missing entries: ' + str(sorted(missing)))
        bad = archive.testzip()
        if bad:
            raise ValueError('APK ZIP integrity failure: ' + bad)
        verify_native_libraries(archive, native_manifest)
        # Match build.sh's distributable inventory. aapt2 can leave hidden
        # compression scratch files beside very large staged model assets;
        # those are neither source assets nor entries in the linked APK.
        expected_assets = {'assets/' + p.relative_to(assets).as_posix(): p
                           for p in assets.rglob('*') if p.is_file()
                           and not any(part.startswith('.') or part in {'node_modules', '__pycache__'}
                                       for part in p.relative_to(assets).parts)}
        actual_assets = {name for name in names
                         if name.startswith('assets/') and not name.endswith('/')}
        if actual_assets != set(expected_assets):
            raise ValueError('APK asset set differs from staged assets')
        for name in names:
            if 'node_modules' in name.split('/'):
                raise ValueError('Development dependency in APK: ' + name)
            if name.endswith('.dex'):
                with archive.open(name) as source:
                    if source.read(4) != b'dex\n':
                        raise ValueError('Invalid DEX ' + name)
        for name, asset in expected_assets.items():
            with archive.open(name) as source, asset.open('rb') as expected:
                if not streams_equal(source, expected):
                    raise ValueError('APK asset bytes differ from staged asset: ' + name)
    return set(names)


def assemble_apk(resources, dex_directory, destination, assets, native_directory=None, native_manifest=None):
    # ZipFile(mode='a') otherwise accepts arbitrary/truncated bytes as a prefix.
    # Never open append mode until the linked input has passed read-only checks.
    resource_names = validate_apk(resources, assets)
    dex_files = sorted(Path(dex_directory).glob('*.dex'))
    if not dex_files or 'classes.dex' not in {p.name for p in dex_files}:
        raise ValueError('No primary Android DEX was produced')
    if resource_names.intersection(p.name for p in dex_files):
        raise ValueError('Linked resource APK already contains Android DEX')
    native_files = {}
    if native_directory is not None:
        if native_manifest is None:
            raise ValueError('JNI packaging requires a pinned runtime manifest')
        native_directory = Path(native_directory)
        native_files = {'lib/' + p.relative_to(native_directory).as_posix(): p
                        for p in native_directory.rglob('*') if p.is_file()}
    elif native_manifest is not None:
        raise ValueError('JNI packaging requires a staged native directory')
    destination = Path(destination)
    created = False
    try:
        with Path(resources).open('rb') as source, destination.open('xb') as output:
            created = True
            shutil.copyfileobj(source, output, CHUNK_BYTES)
            output.flush()
            os.fsync(output.fileno())
        with zipfile.ZipFile(destination, 'a', compression=zipfile.ZIP_DEFLATED,
                             compresslevel=6) as archive:
            for dex in dex_files:
                archive.write(dex, dex.name)
            # zipalign -P 16 places stored native libraries on 16 KiB boundaries.
            for name, native in sorted(native_files.items()):
                archive.write(native, name, compress_type=zipfile.ZIP_STORED)
        with destination.open('rb') as output:
            os.fsync(output.fileno())
        output_names = validate_apk(destination, assets, require_dex=True, native_manifest=native_manifest)
        if output_names != resource_names | {p.name for p in dex_files} | set(native_files):
            raise ValueError('DEX assembly changed resource archive entries')
    except BaseException:
        if created:
            destination.unlink(missing_ok=True)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest='command', required=True)
    validate = subparsers.add_parser('validate')
    validate.add_argument('apk', type=Path)
    validate.add_argument('assets', type=Path)
    validate.add_argument('--require-dex', action='store_true')
    validate.add_argument('--native-manifest', type=Path)
    assemble = subparsers.add_parser('assemble')
    for argument in ('resources', 'dex_directory', 'destination', 'assets'):
        assemble.add_argument(argument, type=Path)
    assemble.add_argument('--native-directory', type=Path)
    assemble.add_argument('--native-manifest', type=Path)
    args = parser.parse_args()
    if args.command == 'validate':
        validate_apk(args.apk, args.assets, args.require_dex, args.native_manifest)
    else:
        assemble_apk(args.resources, args.dex_directory, args.destination, args.assets, args.native_directory, args.native_manifest)
