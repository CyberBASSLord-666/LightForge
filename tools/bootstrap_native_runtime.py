#!/usr/bin/env python3
"""Install and verify official ONNX Runtime binaries against checked-in pins."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import shutil
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'android/native-runtime.json'
DEST = Path(os.environ.get('LIGHTFORGE_TOOLCHAIN_DIR', ROOT.parent / 'toolchain')) / 'onnx'


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def matches(path, expected):
    return path.is_file() and path.stat().st_size == expected['bytes'] and digest(path) == expected['sha256']


def prepare(check=False, stage=None):
    manifest = json.loads(MANIFEST.read_text())
    DEST.mkdir(parents=True, exist_ok=True)
    for kind in ['android', 'host']:
        item = manifest[kind]
        target = DEST / item['name']
        if not matches(target, item):
            if check:
                raise RuntimeError('Missing or changed native dependency: ' + str(target))
            with tempfile.NamedTemporaryFile(dir=DEST, delete=False) as output:
                temp = Path(output.name)
                try:
                    with urllib.request.urlopen(item['url'], timeout=120) as response:
                        shutil.copyfileobj(response, output, 1024 * 1024)
                    output.flush()
                    os.fsync(output.fileno())
                    if not matches(temp, item):
                        raise RuntimeError('Native dependency download integrity failure: ' + item['name'])
                    os.replace(temp, target)
                finally:
                    temp.unlink(missing_ok=True)
    with zipfile.ZipFile(DEST / manifest['android']['name']) as archive:
        if archive.testzip():
            raise RuntimeError('Native runtime AAR CRC failure')
        for relative, item in manifest['files'].items():
            path = Path(relative)
            if path.is_absolute() or '..' in path.parts:
                raise RuntimeError('Unsafe native dependency path: ' + relative)
            target = DEST / path
            if not matches(target, item):
                if check:
                    raise RuntimeError('Missing or changed extracted native dependency: ' + relative)
                content = archive.read(relative)
                if len(content) != item['bytes'] or hashlib.sha256(content).hexdigest() != item['sha256']:
                    raise RuntimeError('Extracted native dependency integrity failure: ' + relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as output:
                    temp = Path(output.name)
                    try:
                        output.write(content)
                        output.flush()
                        os.fsync(output.fileno())
                        os.replace(temp, target)
                    finally:
                        temp.unlink(missing_ok=True)
    if stage is not None:
        stage = Path(stage)
        if stage.exists() and any(stage.iterdir()):
            raise RuntimeError('Native staging directory must be empty: ' + str(stage))
        stage.mkdir(parents=True, exist_ok=True)
        for relative in manifest['files']:
            if relative.startswith('jni/'):
                target = stage / Path(relative).relative_to('jni')
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(DEST / relative, target)
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--stage', type=Path)
    args = parser.parse_args()
    manifest = prepare(args.check, args.stage)
    print('Verified native ONNX Runtime ' + manifest['version'] + ' with ' + str(len(manifest['files']) - 1) + ' JNI libraries.')
