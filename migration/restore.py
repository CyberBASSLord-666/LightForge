#!/usr/bin/env python3
"""Restore original source assets or the signed APK from verified 8 MiB pieces."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parent.parent

def safe_path(root, relative):
    p = PurePosixPath(relative)
    if p.is_absolute() or '..' in p.parts or '\\' in relative:
        raise ValueError('Invalid relative path')
    resolved = (root / p).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError('Path leaves repository')
    return resolved

def restore(root, item):
    destination = safe_path(root, item['path'])
    parts = item['parts']
    if not parts or sum(p['bytes'] for p in parts) != item['bytes']:
        raise ValueError('Invalid total size')
    sources = [safe_path(root, p['path']) for p in parts]
    if destination in sources or len(set(sources)) != len(sources):
        raise ValueError('Duplicate or conflicting paths')
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.' + destination.name, dir=destination.parent)
    digest = hashlib.sha256()
    size = 0
    try:
        with os.fdopen(fd, 'wb') as output:
            for part, source in zip(parts, sources):
                if not 0 < part['bytes'] <= 8 * 1024 * 1024 or source.stat().st_size != part['bytes']:
                    raise ValueError('Invalid part size: ' + part['path'])
                part_digest = hashlib.sha256()
                count = 0
                with source.open('rb') as stream:
                    while block := stream.read(1024 * 1024):
                        count += len(block)
                        if count > part['bytes']:
                            raise ValueError('Part changed during restoration')
                        output.write(block)
                        part_digest.update(block)
                        digest.update(block)
                        size += len(block)
                if count != part['bytes'] or part_digest.hexdigest() != part['sha256']:
                    raise ValueError('Part checksum mismatch: ' + part['path'])
            output.flush()
            os.fsync(output.fileno())
        if size != item['bytes'] or digest.hexdigest() != item['sha256']:
            raise ValueError('Final checksum mismatch: ' + item['path'])
        if item['kind'] == 'apk':
            with zipfile.ZipFile(temporary) as archive:
                if archive.testzip() is not None or not {'AndroidManifest.xml', 'classes.dex', 'resources.arsc'} <= set(archive.namelist()):
                    raise ValueError('APK archive integrity failed')
        os.chmod(temporary, 0o644)
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return {'path': item['path'], 'bytes': size, 'sha256': digest.hexdigest(), 'passed': True}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--only', choices=['source', 'apk', 'all'], default='all')
    args = parser.parse_args()
    manifest = json.loads((ROOT / 'migration/manifest.json').read_text())
    if manifest['schema_version'] != 1:
        raise ValueError('Unsupported manifest')
    result = [restore(ROOT, item) for item in manifest['artifacts']
              if args.only == 'all' or item['kind'] == args.only]
    print(json.dumps(result, indent=2))

if __name__ == '__main__':
    main()
