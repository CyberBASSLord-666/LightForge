#!/usr/bin/env python3
"""Validate linked Android resources before adding dex to a real ZIP archive."""
from pathlib import Path
import argparse
import os
import shutil
import zipfile

CHUNK_BYTES = 1024 * 1024


def streams_equal(first, second):
    while True:
        chunk = first.read(CHUNK_BYTES)
        if chunk != second.read(CHUNK_BYTES):
            return False
        if not chunk:
            return True


def validate_apk(path, assets, require_dex=False):
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


def assemble_apk(resources, dex_directory, destination, assets):
    # ZipFile(mode='a') otherwise accepts arbitrary/truncated bytes as a prefix.
    # Never open append mode until the linked input has passed read-only checks.
    resource_names = validate_apk(resources, assets)
    dex_files = sorted(Path(dex_directory).glob('*.dex'))
    if not dex_files or 'classes.dex' not in {p.name for p in dex_files}:
        raise ValueError('No primary Android DEX was produced')
    if resource_names.intersection(p.name for p in dex_files):
        raise ValueError('Linked resource APK already contains Android DEX')
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
        with destination.open('rb') as output:
            os.fsync(output.fileno())
        output_names = validate_apk(destination, assets, require_dex=True)
        if output_names != resource_names | {p.name for p in dex_files}:
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
    assemble = subparsers.add_parser('assemble')
    for argument in ('resources', 'dex_directory', 'destination', 'assets'):
        assemble.add_argument(argument, type=Path)
    args = parser.parse_args()
    if args.command == 'validate':
        validate_apk(args.apk, args.assets, args.require_dex)
    else:
        assemble_apk(args.resources, args.dex_directory, args.destination, args.assets)
